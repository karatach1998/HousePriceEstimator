import bisect
import os
import re
from datetime import datetime
from operator import itemgetter

import geopy
import requests
import streamlit as st
from pyecharts import options as opts
from pyecharts.charts import Bar, Line, WordCloud
from pyecharts.commons.utils import JsCode
from pyecharts.globals import ThemeType
from streamlit_echarts import st_pyecharts

from utils.streamlit_pills import pills
from utils.ymap_component import ymap_component


st.set_page_config(
    page_icon="./static/favicon.ico",
)

is_new = lambda: 'apartment_type' not in st.session_state or st.session_state.apartment_type == 0

LABELS = {
    'appartment_type': "Тип жилья",
    'building_type': "Тип дома",
    'build_year': "Год постройки",
    'floor': "Этаж",
    'max_floor': "Этажей в доме",
    'num_room': "Количество комнат",
    'height': "Высота потолков",
    'decorating': "Тип отделки" if is_new() else "Тип ремонта",
    'full_sq': "Общая площадь",
    # 'appartment_type': "Тип жилья",
    # 'appartment_type': "Тип жилья",
}


def build_price_title_chart(*, total):
    word_cloud = WordCloud()
    word_cloud.add("", [(f"{total:,} руб", 100)], shape='cardioid',
                   tooltip_opts=opts.TooltipOpts(axis_pointer_type='shadow',
                                                 position='inside',
                                                 formatter=JsCode(r"function(x){return `Оценочная цена составила ${x.name.replaceAll(',', ' ')}`;}")))
    return word_cloud


def build_price_components_impact_chart(*, total, details):
    bar = Bar(init_opts=opts.InitOpts(theme=ThemeType.WALDEN))
    bar.add_xaxis(['_'])
    for key, impact_fraq in details.items():
        bar.add_yaxis(LABELS[key], [dict(value=int(impact_fraq*100), priceImpact=int(total*impact_fraq))], stack='house_price')
    bar.reversal_axis()
    bar.set_global_opts(
        title_opts=opts.TitleOpts(title="Состав цены:", text_align='center', pos_top='center',
                                  title_textstyle_opts=opts.TextStyleOpts(color='#fff', font_size=16)),
        legend_opts=opts.LegendOpts(is_show=False),
        xaxis_opts=opts.AxisOpts(is_show=False),
        yaxis_opts=opts.AxisOpts(is_show=False),
    )
    bar.set_series_opts(
        itemstyle_opts=dict(barBorderRadius=5, borderWidth=3),
        label_opts=opts.LabelOpts(font_size=14, font_family="Microsoft YaHei",
                                  formatter=JsCode(r'''function(x){ return `${x.seriesName} ${x.value}%`; }''')),
        tooltip_opts=opts.TooltipOpts(position='inside', formatter=JsCode(r'''
        function(x){
            return
            `Вклад компонента "${x.seriesName}"</br>
            в стоимость составил</br>
            ${x.data.priceImpact.toLocaleString()} руб (${x.value}%)`;
        }
        '''), textstyle_opts=opts.TextStyleOpts(width='70px', height='70px')),
        emphasis=dict(itemStyle=dict(shadowBlur=20, shadowColor='rgba(0, 0, 0, 0.3)'))
    )
    return bar


def build_price_dynamic_chart(*, price_flow):
    background_color_js = (
        "new echarts.graphic.LinearGradient(0, 0, 0, 1, "
        "[{offset: 0, color: '#c86589'}, {offset: 1, color: '#06a7ff'}], false)"
    )
    history_area_color = {
        'type': "linear",
        'x': 0,
        'y': 0,
        'x2': 0,
        'y2': 1,
        'colorStops': [
            {'offset': 0, 'color': '#c86589'},
            {'offset': 1, 'color': '#06a7ff'},
        ]
    }
    predict_area_color_js = (
        "new echarts.graphic.LinearGradient(0, 0, 0, 1, "
        "[{offset: 0, color: '#eb64fb'}, {offset: 1, color: '#3fbbff0d'}], false)"
    )
    line = Line()
    line.add_xaxis(xaxis_data=[p['date'].strftime('%Y-%m-%d') for p in price_flow])
    line.add_yaxis(
        "История цены",
        y_axis=[p['price'] for p in price_flow],
        is_smooth=True,
        is_symbol_show=True,
        symbol='circle',
        symbol_size=8,
        # linestyle_opts=opts.LineStyleOpts(color='#fff'),
        # label_opts=opts.LabelOpts(is_show=True, position='top', color='white'),
        # itemstyle_opts=opts.ItemStyleOpts(
        #     color='red', border_color='#fff', border_width=3
        # ),
        tooltip_opts=opts.TooltipOpts(is_show=False),
        areastyle_opts=opts.AreaStyleOpts(color=history_area_color, opacity=1)
    )
    line.set_global_opts(
        xaxis_opts=opts.AxisOpts(
            type_='category',
            boundary_gap=False,
            axislabel_opts=opts.LabelOpts(rotate=60),
        ),
        yaxis_opts=opts.AxisOpts(
            type_='value',
            axispointer_opts=opts.AxisPointerOpts(is_show=True, type_='shadow'),
        )
    )
    return line


def build_competitive_price_chart(target_sale_desc, similar_sales_desc):
    offers_details = sorted(similar_sales_desc, key=itemgetter('price'))
    target_sale_desc_index = bisect.bisect(offers_details, target_sale_desc['price'], key=itemgetter('price'))
    offers_details.insert(target_sale_desc_index, target_sale_desc)

    bar = Bar(dict(pos_right='50%'))
    bar.add_xaxis([dict(value=str(index), axisLabel={'fontWeight': 'bold' if index == target_sale_desc_index else 'normal'})#, axisPointer=dict(type='shadow', shadowStyle=dict(color='rgba(1,0,0,0.1)')) if index == target_sale_desc_index else dict())
                   for index, offer in enumerate(offers_details)])
    for key in target_sale_desc['details'].keys():
        bar.add_yaxis(
            LABELS[key],
            y_axis=[dict(offer['details'][key], value=int(offer['price']*offer['details'][key]['impact']))
                    for index, offer in enumerate(offers_details)],
            stack='components',
            category_gap='50%',
            label_opts=opts.LabelOpts(is_show=False, position='inside', font_size=12, font_family="Microsoft YaHei",
                                      formatter=JsCode(r'''function(x){return `${x.data.originalValue}`;}''')),
        )
    # bar_price = Bar()
    # bar_price.add_xaxis([dict(value=offer['address'], label={'fontWeight': 'bolder' if index == target_sale_desc_index else 'normal'}) for index, offer in enumerate(offers_details)])
    bar.add_yaxis(
        "Стоимость",
        y_axis=[dict(value=0, price=offer['price'], label={'fontWeight': 'bold' if index == target_sale_desc_index else 'normal'})
                for index, offer in enumerate(offers_details)],
        stack='components',
        is_selected=True,
        # background_style=dict(opacity=0),
        label_opts=opts.LabelOpts(position='right', distance=10, font_size=18, font_weight='bolder', font_family='Microsoft YaHei',
                                  formatter=JsCode(r'''function(x){return `${x.data.price}`;}''')),
        # emphasis=dict(label=dict(fontWeight='bold'))
    )
    bar.options.get("legend")[0].get("data").remove("Стоимость")
    # bar = bar.overlap(bar_price)
    bar.reversal_axis()
    bar.set_global_opts(
        xaxis_opts=opts.AxisOpts(
            type_='value',
            axislabel_opts=opts.LabelOpts(rotate=45, formatter="{value} руб")
        ),
        yaxis_opts=opts.AxisOpts(
            type_='category',
            axispointer_opts=opts.AxisPointerOpts(is_show=True, type_='shadow'),
        ),
    )
    bar.set_series_opts(
        itemstyle_opts=dict(barBorderRadius=3, borderWidth=3),
        # tooltip_opts=opts.TooltipOpts(trigger='axis', position='inside', formatter=JsCode(r'''
        # function(x){
        #     return
        #     `${x.seriesName} = ${x.data.originalValue}</br>
        #     Вклад в стоимость - ${Number(x.impact*100).toFixed()}%</br>
        #     т. е. ${x.value} руб`;
        # }
        # '''), textstyle_opts=opts.TextStyleOpts(width='70px', height='70px')),
        emphasis=dict(focus='series'),
    )
    return bar


st.title("Калькулятор стоимости жилья")
# pos = None
# if pos is None:
ymap_component("Выбирите расположение дома", initial=dict(latitude=55.769359, longitude=37.588234), key='coords')
# if st.session_state.coords is not None:
#     st.info("%(latitude)f, %(longitude)f" % dict(st.session_state.coords))
address_info = geopy.geocoders.Nominatim(user_agent="HousePriceEstimator").reverse("%(latitude)f, %(longitude)f" % st.session_state.coords) if st.session_state.coords is not None else None
st.text_input("Адрес дома", value=getattr(address_info, 'address', None), disabled=True)
district = address_info and address_info.raw['address']['suburb']
if district != "Пресненский район":
    st.error("На данный момент возможна оценка недвижимости только в Пресненском районе Москвы")
# coords = address_info and dict(latitude=address_info.latitude, longitude=address_info.longitude)
# else:
#     pos = ymap_component(pos)

apartment_types = (
    "Новостройка",
    "Вторичка",
)
pills("Тип жилья", apartment_types, key='apartment_type')

building_types = (
    "Монолитный",
    "Монолитно-кирпичный"
)
pills("Тип дома", building_types, key='building_type')

st.number_input(
    "Год постройки/сдачи",
    min_value=1800, max_value=datetime.now().year+5,
    value=datetime.now().year,
    key='build_year'
)

st.slider(
    "Номер этажа квартиры",
    min_value=1, max_value=100,#st.session_state.get('max_floor', 100),
    key='floor'
)
st.slider(
    "Этажей в доме",
    min_value=1, max_value=100, value=20,
    key='max_floor'
)
if st.session_state.floor > st.session_state.max_floor:
    st.error(f"Указанный номер этажa превышает количество этажей в доме")

st.select_slider(
    "Количество комнат",
    ["Студия"] + list(map(str, range(1, 20))) + ["20+"],
    key='num_room'
)

st.number_input(
    "Высота потолков",
    min_value=1.0, max_value=10.0, step=0.1, value=3.0,
    format='%.1f',
    key='height'
)

decorating_types_new = (
    "Без отделки",
    "Чистовая",
    "Предчистовая",
    "Под ключ",
)
decorating_types_old = (
    "Без отделки",
    "Дизайнерский",
)
decorating_types = decorating_types_new if is_new() else decorating_types_old
pills(LABELS['decorating'], decorating_types, key='decorating')

st.number_input(
    "Общая площадь",
    min_value=1.0, max_value=500.0, step=0.5, value=50.0,
    format='%.1f',
    key='full_sq'
)

required_parameters = (
    'build_year', 'num_room', 'height', 'floor', 'max_floor', 'full_sq',
    'apartment_type', 'building_type', 'decorating',
)
if not all(map(lambda p: p in st.session_state and st.session_state[p] is not None, required_parameters)):
    st.info("Укажите необходимые параметры квартиры")
    st.session_state.pop('calculation_performed', None)
else:
    calculation_performed = st.session_state.get('calculation_performed')
    st.session_state.calculation_performed = st.button("Расчитать стоимость", type='primary', use_container_width=True)
    if st.session_state.calculation_performed:
        st.subheader("Результат оценки")
        with st.spinner("Расчет стоимости..."):
            sale_info = dict(
                (
                    (key, st.session_state[key]) for key in (
                        'build_year', 'height', 'floor', 'max_floor', 'full_sq',
                    )
                ),
                num_room=(int(st.session_state.num_room) if re.match(r"\d+", st.session_state.num_room) else 0) if st.session_state.num_room is not None else None,
                district=district,
                apartment_type=apartment_types[st.session_state.apartment_type],
                building_type=building_types[st.session_state.building_type],
                decorating=decorating_types[st.session_state.decorating]
            )
            data = dict(coords=st.session_state.coords, sale_info=sale_info)
            r = requests.post(f"{os.getenv('MODEL_SERVER_BASE_URL')}/predict_price", params=dict(top_features=5), json=data)
            predicted_price = r.json()
            st_pyecharts(build_price_title_chart(total=predicted_price['total']), height=50)
            st_pyecharts(build_price_components_impact_chart(total=predicted_price['total'], details=predicted_price['details']), height=400)
            # total = 5400000
            # details = {'build_year': 0.60, 'num_room': 0.30, 'floor': 0.10}
            # st_pyecharts(build_price_title_chart(total=total), height=50)
            # st_pyecharts(build_price_components_impact_chart(total=total, details=details), height=400)
        # import time
        # time.sleep(2)
        # st.subheader("Динамика цены квартиры с указанными параметрами")
        # with st.spinner("Построение тренда..."):
        #     price_flow = [
        #         dict(date=datetime(2023, 3, 3), price=5_200_000),
        #         dict(date=datetime(2023, 3, 5), price=5_300_000),
        #         dict(date=datetime(2023, 3, 7), price=5_400_000),
        #         dict(date=datetime(2023, 3, 9), price=5_250_000),
        #         dict(date=datetime(2023, 3, 11), price=5_450_000),
        #         dict(date=datetime(2023, 3, 13), price=5_400_000),
        #     ]
        #     st_pyecharts(build_price_dynamic_chart(price_flow=price_flow))
        # import time
        # time.sleep(2)
        st.subheader("Похожие предложения")
        with st.spinner("Подбор альтернатив..."):
            sale_info = dict(
                (
                    (key, st.session_state[key]) for key in (
                        'build_year', 'height', 'floor', 'max_floor', 'full_sq',
                    )
                ),
                num_room=(int(st.session_state.num_room) if re.match(r"\d+", st.session_state.num_room) else 0) if st.session_state.num_room is not None else None,
                district=district,
                apartment_type=apartment_types[st.session_state.apartment_type],
                building_type=building_types[st.session_state.building_type],
                decorating=decorating_types[st.session_state.decorating]
            )
            data = dict(coords=st.session_state.coords, sale_info=sale_info)
            r = requests.post(f"{os.getenv('MODEL_SERVER_BASE_URL')}/find_similar", params=dict(top_similar_items=4, top_features=5), json=data)
            sales_desc = r.json()
            # T = lambda impact, value: dict(impact=impact, originalValue=value)
            # price_details = {k: T(v, data[k]) for k, v in data.items()}
            # target_offer = dict(details=price_details, price=data, address="Адрес X")
            # similar_offers_details = [
            #     {'details': {'build_year': T(0.40, 1960), 'num_room': T(0.50, 3), 'floor': T(0.10, 5)}, 'price': 6_000_000, 'address': "Адрес 1"},
            #     {'details': {'build_year': T(0.55, 1993), 'num_room': T(0.40, 2), 'floor': T(0.05, 5)}, 'price': 4_850_000, 'address': "Адрес 2"},
            #     {'details': {'build_year': T(0.60, 2012), 'num_room': T(0.38, 1), 'floor': T(0.02, 10)}, 'price': 5_200_000, 'address': "Адрес 3"},
            #     {'details': {'build_year': T(0.58, 2009), 'num_room': T(0.37, 1), 'floor': T(0.05, 12)}, 'price': 5_250_000, 'address': "Адрес 4"},
            # ]
            st_pyecharts(build_competitive_price_chart(
                target_sale_desc=sales_desc['target'],
                similar_sales_desc=sales_desc['similar']
            ), height='500px')
        # fig = None
        # st.plotly_chart(fig, theme=None, use_container_width=True)

st.header("Задействованные технологии")
st.markdown("""
<div style="width: 740; display: inline-flex; flex-direction: row; flex-wrap: wrap; align-items: center; justify-content: center; gap: 50px">
    <img src="https://s4-recruiting.cdn.greenhouse.io/external_greenhouse_job_boards/logos/400/515/800/original/logo-clickhouse.png?1634065357" height="100px">
    <img src="https://upload.wikimedia.org/wikipedia/commons/d/de/AirflowLogo.png" height="100px">
    <img src="https://d1.awsstatic.com/PAC/kuberneteslogo.eabc6359f48c8e30b7a138c18177f3fd39338e05.png" height="100px">
    <img src="https://i.pinimg.com/originals/27/42/47/274247632a09f3a7750c2c6f43de403a.png" height="100px">
    <img src="https://upload.wikimedia.org/wikipedia/en/thumb/6/6b/Redis_Logo.svg/1200px-Redis_Logo.svg.png" height="100px">
    <img src="https://boostlog.io/articles/5abb7c910814730093a2eeb5/images-1522236577198.jpg" height="100px">
    <img src="https://i2.wp.com/blog.knoldus.com/wp-content/uploads/2020/09/selenium_logo_large.png?fit=2932%2C718&amp;ssl=1" height="100px">
</div>
""", unsafe_allow_html=True)

st.header("Репозиторий проекта")
st.markdown("""
<div style="width: 600; display: flex; align-items: center; justify-content: center">
    <a href="https://github.com/karatach1998/HousePriceEstimator">
        <img src="https://gitlab.com/uploads/-/system/group/avatar/10532272/github.png" alt="github.com/karatach1998/HousePriceEstimator" style="width: 70px">
    </a>
</div>
""", unsafe_allow_html=True)