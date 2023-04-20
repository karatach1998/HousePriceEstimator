import requests
from airflow import DAG
from airflow.decorators import task
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import KuberntesPodOperator
from airflow.exceptions import AirflowFailException
from rabbitmq_provider.hooks.rabbitmq import RabbitMQHook
from kubernetes import config, client, models as k8s, watch


selenium_hub_pod = (
    k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(
            labels=dict(app="selenium-hub")
        ),
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    image="selenium/hub:4.8",
                    image_pull_policy="IfNotPresent",
                    ports=[
                        k8s.V1ContainerPort(container_port=4442, name="event-bus-publish-port"),
                        k8s.V1ContainerPort(container_port=4443, name="event-bus-subscribe-port"),
                        k8s.V1ContainerPort(container_port=4444, name="selenium-hub-port"),
                    ]
                )
            ]
        )
    )
)

selenium_hub_service = (
    k8s.V1Service(
        metadata=k8s.V1ObjectMeta(
            name="selenium"
        ),
        spec=k8s.V1ServiceSpec(
            type='ClusterIP',
            selector=dict(app="selenium-hub"),
            ports=[
                k8s.V1ServicePort(port=4444, target_port="selenium-hub-port"),
            ]
        )
    )
)

selenium_node_deployment = (
    k8s.V1Deployment(
        metadata=k8s.V1PodTemplateSpec(
            name="selenium-node"
        ),
        spec=k8s.V1DeploymentSpec(
            replicas=2,
            selector=k8s.V1LabelSelector(
                match_labels=dict(app="selenium-node")
            ),
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(
                    labels=dict(app="selenium-node")
                ),
                spec=k8s.V1PodSpec(
                    containers=[
                        k8s.V1Container(
                            image="selenium/node-chrome:4.8",
                            image_pull_policy="IfNotPresent",
                            env=[
                                k8s.V1EnvVar(name="SE_EVENT_BUS_HOST", value="selenium"),
                                k8s.V1EnvVar(name="SE_EVENT_BUS_PUBLISH_PORT", value=4442),
                                k8s.V1EnvVar(name="SE_EVENT_BUS_SUBSCRIBE_PORT", value=4443),
                                k8s.V1EnvVar(name="SE_NODE_HOST", value_from=k8s.V1EnvVarSource(field_ref=k8s.V1ObjectFieldSelector(field_path="status.podIP"))),
                                k8s.V1EnvVar(name="JAVA_OPTS", value="-Dwebdriver.chrome.whitelistedIps="),
                                k8s.V1EnvVar(name="SE_NODE_MAX_SESSIONS", value=10),
                                k8s.V1EnvVar(name="SE_NODE_OVERRIDE_MAX_SESSIONS", value="true"),
                            ],
                            resources=k8s.V1ResourceRequirements(requests=dict(memory='2g')),
                        )
                    ]
                )
            )
        )
    )
)

selenium_node_hpa = (
    k8s.V2HorizontalPodAutoscaler(
        spec=k8s.V2HorizontalPodAutoscalerSpec(
            scale_target_ref=k8s.V2CrossVersionObjectReference(
                kind='Deployment',
                name="selenium-node"
            ),
            min_replicas=3,
            max_replicas=10,
            metrics=[
                k8s.V2MetricSpec(
                    type='Resource',
                    resource=k8s.V2ResourceMetricSource(
                        name='cpu',
                        target=k8s.V2MetricTarget(
                            type='Utilization',
                            average_utilization=50,
                        )
                    )
                ),
            ]
        )
    )
)


class RabbitMQEmptySensor():
    def __init__(self, queue_name):
        super(RabbitMQEmptySensor, self).__init__()
        self.queue_name = queue_name

    def poke(self):
        hook = RabbitMQHook("rabbitmq")
        q = hook.declare_queue(self.queue_name, passive=True)
        return q.method.message_count == 0


with DAG(dag_id="collect_and_finetune", schedule="*/2 * * * *") as dag:
    kube_namespace = "scrapper"

    @task
    def create_selenium_hub():
        config.load_incluster_config()
        core_api = client.CoreV1Api()
        core_api.create_namespaced_pod(body=selenium_hub_pod, namespace=kube_namespace)
        core_api.create_namespaced_service(body=selenium_hub_service, namespace=kube_namespace)
        w = watch.Watch()
        for event in w.stream(core_api.list_namespaced_pods, label_selector="app=selenium-hub", namespace=kube_namespace):
            if any(c.type == "Ready" and c.status == "True" for c in event["object"].status.conditions):
                break
        else:
            raise AirflowFailException()

    @task
    def create_selenium_node():
        config.load_incluster_config()
        apps_api = client.AppsV1Api()
        apps_api.create_namespaced_deployment(body=selenium_node_deployment, namespace=kube_namespace)
        client.AutoscalingV2Api().create_namespaced_horizontal_pod_autoscaler(body=selenium_node_hpa, namespace=kube_namespace)
        w = watch.Watch()
        for event in w.stream(apps_api.list_namespaced_deployment, field_selector="name=selenium-node", namespace=kube_namespace):
            if event['object'].status.ready_replicas >= 1:
                break
        else:
            raise AirflowFailException()

    @task
    def delete_selenium_hub():
        config.load_incluster_config()
        core_api = client.AppsV1Api()
        core_api.delete_namespaced_service(body=selenium_hub_service, namespace=kube_namespace)
        core_api.delete_namespaced_pod(body=selenium_hub_pod, namespace=kube_namespace)

    @task
    def delete_selenium_node():
        config.load_incluster_config()
        client.AutoscalingV2Api().delete_namespaced_horizontal_pod_autoscaler(body=selenium_node_hpa, namespace=kube_namespace)
        client.AppsV1Api().delete_namespaced_deployment(body=selenium_node_deployment, namespace=kube_namespace)

    scrapper_producer = KuberntesPodOperator(
        task_id="scrape_offers_list",
        namespace=kube_namespace,
        image="ghcr.io/karatach1998/toolbox:latest",
        image_pull_policy="Always",
        cmds=["poetry", "run", "python", "toolbox/cian_scrapper.py"],
        name="scrapper_producer",
        is_delete_operator_pod=True,
        env_vars={
            "BROKER_URL": r"amqp://{{ conn.rabbitmq.login }}:{{ conn.rabbitmq.password }}@{{ conn.rabbitmq.host }}:{{ conn.rabbitmq.port }}/",
            "SELENIUM_REMOTE_URL": "http://selenium:4444/wd/hub",
        },
    )
    scrapper_worker = KuberntesPodOperator(
        task_id="scrape_offers_info",
        namespace=kube_namespace,
        image="ghcr.io/karatach1998/toolbox:latest",
        image_pull_policy="Always",
        cmds=["poetry", "run", "celery", "-A toolbox.cian_scrapper.celeryapp", "worker", "-P celery_pool_asyncio:TaskPool"],
        name="scrapper_worker",
        is_delete_operator_pod=True,
        env_vars={
            "BROKER_URL": r"amqp://{{ conn.rabbitmq.login }}:{{ conn.rabbitmq.password }}@{{ conn.rabbitmq.host }}:{{ conn.rabbitmq.port }}/",
            "SELENIUM_REMOTE_URL": "http://selenium:4444/wd/hub",
        },
    )

    tasks_queue_empty = RabbitMQEmptySensor("tasks")
    sales_infos_queue_empty = RabbitMQEmptySensor("sales_infos")

    @task
    def finetune_model():
        return requests.get("model-server:8080/finetune").status_code == 200

    (
        create_selenium_hub() >> create_selenium_node()
        >> [scrapper_producer, scrapper_worker]
        >> tasks_queue_empty 
        >> delete_selenium_node() >> delete_selenium_hub()
        >> sales_infos_queue_empty
        >> finetune_model()
    )