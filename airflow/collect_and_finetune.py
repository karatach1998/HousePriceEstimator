import logging
from datetime import datetime

import requests
from airflow import DAG
from airflow.decorators import task
from airflow.exceptions import AirflowFailException
from airflow.models.baseoperator import chain, cross_downstream
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import KubernetesPodOperator
from airflow.providers.http.sensors.http import HttpSensor
from jinja2 import Template
from kubernetes import config, client, watch
from kubernetes.client import models as k8s 


logger = logging.getLogger("airflow.task")

kube_namespace = "scrapper"

namespace = (
    k8s.V1Namespace(
        metadata=k8s.V1ObjectMeta(
            name=kube_namespace
        )
    )
)

selenium_hub_pod = (
    k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(
            name="selenium-hub",
            labels=dict(app="selenium-hub")
        ),
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="hub",
                    image="selenium/hub:4.8",
                    image_pull_policy="IfNotPresent",
                    ports=[
                        k8s.V1ContainerPort(container_port=4442, name="publish-port"),
                        k8s.V1ContainerPort(container_port=4443, name="subscribe-port"),
                        k8s.V1ContainerPort(container_port=4444, name="selenium-port"),
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
                k8s.V1ServicePort(port=4442, target_port="publish-port", name="publish-port"),
                k8s.V1ServicePort(port=4443, target_port="subscribe-port", name="subscribe-port"),
                k8s.V1ServicePort(port=4444, target_port="selenium-port", name="selenium-port"),
            ]
        )
    )
)

selenium_node_deployment = (
    k8s.V1Deployment(
        metadata=k8s.V1ObjectMeta(
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
                            name="node",
                            image="selenium/node-firefox:4.8",
                            image_pull_policy="IfNotPresent",
                            env=[
                                k8s.V1EnvVar(name="SE_EVENT_BUS_HOST", value="selenium"),
                                k8s.V1EnvVar(name="SE_EVENT_BUS_PUBLISH_PORT", value="4442"),
                                k8s.V1EnvVar(name="SE_EVENT_BUS_SUBSCRIBE_PORT", value="4443"),
                                k8s.V1EnvVar(name="SE_NODE_HOST", value_from=k8s.V1EnvVarSource(field_ref=k8s.V1ObjectFieldSelector(field_path="status.podIP"))),
                                k8s.V1EnvVar(name="JAVA_OPTS", value="-Dwebdriver.chrome.whitelistedIps="),
                                k8s.V1EnvVar(name="SE_NODE_MAX_SESSIONS", value="10"),
                                k8s.V1EnvVar(name="SE_NODE_OVERRIDE_MAX_SESSIONS", value="true"),
                            ],
                            resources=k8s.V1ResourceRequirements(requests=dict(memory='2G')),
                        )
                    ]
                )
            )
        )
    )
)

selenium_node_hpa = (
    k8s.V2HorizontalPodAutoscaler(
        metadata=k8s.V1ObjectMeta(
            name="selenium-node",
        ),
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

scrapper_worker_pod = lambda conn: (
    k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(
            name="scrapper-worker",
        ),
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="celery",
                    image="ghcr.io/karatach1998/cian-scrapper:latest",
                    image_pull_policy="Always",
                    command=["/bin/sh", "-c", "ls -l . ; poetry run celery -A cian_scrapper.main.celeryapp worker"],
                    env=[
                        k8s.V1EnvVar(name="BROKER_URL", value=Template(r"amqp://{{ conn.rabbitmq_default.login }}:{{ conn.rabbitmq_default.password }}@{{ conn.rabbitmq_default.host }}:{{ conn.rabbitmq_default.port }}/").render(conn=conn)),
                        # k8s.V1EnvVar(name="CELERY_CUSTOM_WORKER_POOL", value="celery_aio_pool.pool:AsyncIOPool"),
                        k8s.V1EnvVar(name="CELERY_DEFAULT_QUEUE", value="tasks"),
                        k8s.V1EnvVar(name="CELERY_IGNORE_RESULT", value="True"),
                        k8s.V1EnvVar(name="CLICKHOUSE_HOST", value=conn.clickhouse_default.host),
                        k8s.V1EnvVar(name="CLICKHOUSE_USER", value=conn.clickhouse_default.login),
                        k8s.V1EnvVar(name="CLICKHOUSE_PASSWORD", value=conn.clickhouse_default.password),
                        k8s.V1EnvVar(name="GEOINFO_BASE_URL", value="http://geoinfo.default.svc.cluster.local:8060"),
                        k8s.V1EnvVar(name="SELENIUM_REMOTE_URL", value="http://selenium:4444/wd/hub"),
                    ]
                )
            ],
        )
    )
)

scrapper_flower_pod = lambda conn: (
    k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(
            name="scrapper-flower",
            labels=dict(app="scrapper-flower")
        ),
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="celery",
                    image="ghcr.io/karatach1998/cian-scrapper:latest",
                    image_pull_policy="Always",
                    command=["/bin/sh", "-c", "poetry run celery -A cian_scrapper.main.celeryapp flower --address=0.0.0.0 --port=5555"],
                    ports=[
                        k8s.V1ContainerPort(container_port=5555),
                    ],
                    env=[
                        k8s.V1EnvVar(name="BROKER_URL", value=Template(r"amqp://{{ conn.rabbitmq_default.login }}:{{ conn.rabbitmq_default.password }}@{{ conn.rabbitmq_default.host }}:{{ conn.rabbitmq_default.port }}/").render(conn=conn)),
                        k8s.V1EnvVar(name="CLELERY_DEFAULT_QUEUE", value="tasks"),
                    ]
                )
            ]
        )
    )
)

scrapper_flower_svc = (
    k8s.V1Service(
        metadata=k8s.V1ObjectMeta(
            name="scrapper-flower"
        ),
        spec=k8s.V1ServiceSpec(
            type='ClusterIP',
            selector=dict(app="scrapper-flower"),
            ports=[
                k8s.V1ServicePort(port=5555, target_port=5555),
            ]
        )
    )
)


with DAG(dag_id="collect_and_finetune", start_date=datetime(2023, 5, 30), schedule="10 * * * *") as dag:
    @task
    def create_selenium_hub():
        config.load_incluster_config()
        core_api = client.CoreV1Api()
        core_api.create_namespace(body=namespace)
        core_api.create_namespaced_pod(body=selenium_hub_pod, namespace=kube_namespace)
        core_api.create_namespaced_service(body=selenium_hub_service, namespace=kube_namespace)
        w = watch.Watch()
        for event in w.stream(core_api.list_namespaced_pod, label_selector="app=selenium-hub", namespace=kube_namespace):
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
        for event in w.stream(apps_api.list_namespaced_deployment, field_selector="metadata.name=selenium-node", namespace=kube_namespace):
            if event['object'].status.ready_replicas is not None and event['object'].status.ready_replicas >= 1:
                break
        else:
            raise AirflowFailException()
    
    @task
    def create_scrapper_worker(**kwargs):
        config.load_incluster_config()
        core_api = client.CoreV1Api()
        core_api.create_namespaced_pod(body=scrapper_worker_pod(kwargs.get('conn')), namespace=kube_namespace)
        core_api.create_namespaced_pod(body=scrapper_flower_pod(kwargs.get('conn')), namespace=kube_namespace)
        core_api.create_namespaced_service(body=scrapper_flower_svc, namespace=kube_namespace)

    @task
    def delete_selenium_hub():
        config.load_incluster_config()
        core_api = client.CoreV1Api()
        core_api.delete_namespaced_service(name="selenium", namespace=kube_namespace)
        core_api.delete_namespaced_pod(name="selenium-hub", namespace=kube_namespace)
        core_api.delete_namespace(name=kube_namespace)

    @task
    def delete_selenium_node():
        config.load_incluster_config()
        client.AutoscalingV2Api().delete_namespaced_horizontal_pod_autoscaler(name="selenium-node", namespace=kube_namespace)
        client.AppsV1Api().delete_namespaced_deployment(name="selenium-node", namespace=kube_namespace)
    
    @task
    def delete_scrapper_worker():
        config.load_incluster_config()
        core_api = client.CoreV1Api()
        core_api.delete_namespaced_service(name="scrapper-flower", namespace=kube_namespace)
        core_api.delete_namespaced_pod(name="scrapper-flower", namespace=kube_namespace)
        core_api.delete_namespaced_pod(name="scrapper-worker", namespace=kube_namespace)

    scrapper_producer = KubernetesPodOperator(
        task_id="scrape_sales_list",
        namespace=kube_namespace,
        image="ghcr.io/karatach1998/cian-scrapper:latest",
        image_pull_policy="Always",
        cmds=["poetry", "run", "python", "cian_scrapper/main.py"],
        name="scrapper_producer",
        startup_timeout_seconds=300,
        is_delete_operator_pod=True,
        env_vars={
            "BROKER_URL": r"amqp://{{ conn.rabbitmq_default.login }}:{{ conn.rabbitmq_default.password }}@{{ conn.rabbitmq_default.host }}:{{ conn.rabbitmq_default.port }}/",
            "CELERY_DEFAULT_QUEUE": "tasks",
            "SCRAPPER_RESULTS_TABLE": "sales_info",
            "SELENIUM_REMOTE_URL": "http://selenium:4444/wd/hub",
        },
    )

    all_tasks_processed = [
        HttpSensor(
            task_id=f'left_{state}_tasks',
            http_conn_id='http_flower',
            endpoint=f"/api/tasks?state={state}",
            response_check=lambda response: len(response.json()) == 0
        ) for state in ('PENDING', 'RECEIVED', 'STARTED')
    ]

    @task
    def finetune_model():
        return requests.get("model-server:8100/finetune").status_code == 200

    chain(
        create_selenium_hub(), create_selenium_node(),
        create_scrapper_worker(), scrapper_producer, all_tasks_processed,
        delete_scrapper_worker(), delete_selenium_node(), delete_selenium_hub(),
        finetune_model()
    )