import bisect
from datetime import datetime
from operator import itemgetter

import streamlit as st
from pyecharts import options as opts
from pyecharts.charts import Bar, Line, WordCloud
from pyecharts.commons.utils import JsCode
from pyecharts.globals import ThemeType
from streamlit_echarts import st_pyecharts

from utils.streamlit_pills import pills
from utils.ymap_component import ymap_component


is_new = lambda: 'appartment_type' not in st.session_state or st.session_state.appartment_type != 0

LABELS = {
    'appartment_type': "Тип жилья",
    'material': "Тип дома",
    'build_year': "Год постройки",
    'floor': "Этаж",
    'max_floor': "Этажей в доме",
    'num_room': "Количество комнат",
    'height': "Высота потолков",
    'decorating': "Тип отделки" if is_new() else "Тип ремонта",
    # 'appartment_type': "Тип жилья",
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


def build_price_components_imact_chart(*, total, details):
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


def build_competitive_price_chart(target_offer, similar_offers_details):
    offers_details = sorted(similar_offers_details, key=itemgetter('price'))
    target_offer_index = bisect.bisect(offers_details, target_offer['price'], key=itemgetter('price'))
    offers_details.insert(target_offer_index, target_offer)

    bar = Bar(dict(pos_right='50%'))
    bar.add_xaxis([dict(value=offer['address'], axisLabel={'fontWeight': 'bold' if index == target_offer_index else 'normal'})#, axisPointer=dict(type='shadow', shadowStyle=dict(color='rgba(1,0,0,0.1)')) if index == target_offer_index else dict())
                   for index, offer in enumerate(offers_details)])
    for key in target_offer['details'].keys():
        bar.add_yaxis(
            LABELS[key],
            y_axis=[dict(offer['details'][key], value=offer['price']*offer['details'][key]['impact'])
                    for index, offer in enumerate(offers_details)],
            stack='components',
            category_gap='50%',
            label_opts=opts.LabelOpts(position='inside', font_size=12, font_family="Microsoft YaHei",
                                      formatter=JsCode(r'''function(x){return `${x.data.originalValue}`;}''')),
        )
    # bar_price = Bar()
    # bar_price.add_xaxis([dict(value=offer['address'], label={'fontWeight': 'bolder' if index == target_offer_index else 'normal'}) for index, offer in enumerate(offers_details)])
    bar.add_yaxis(
        "Стоимость",
        y_axis=[dict(value=0, price=offer['price'], label={'fontWeight': 'bolder' if index == target_offer_index else 'normal'})
                for index, offer in enumerate(offers_details)],
        stack='components',
        is_selected=True,
        # background_style=dict(opacity=0),
        label_opts=opts.LabelOpts(position='right', distance=10, font_size=16, font_weight='bolder', font_family='Microsoft YaHei',
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
ymap_component("Выбирите расположение дома", key='pos')
st.text_input("Адрес дома", value='', disabled=True)
# else:
#     pos = ymap_component(pos)

appartment_types = (
    "Новостройка",
    "Вторичка",
)
pills("Тип жилья", appartment_types, key='appartment_type')

materials = (
    'Кирпичный',
    'Монолитный',
    'Блочный',
)
pills("Тип дома", materials, key='material')

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
    "Черновая",
)
decorating_types_old = (
    "Квартира без ремонта",
    "Косметический",
    "Евро",
    "Дизайнерский",
)
pills(
    LABELS['decorating'],
    decorating_types_new if is_new() else decorating_types_old,
    key='decorating',
)

if not st.session_state.get('is_filled', False):
    st.info("Укажите необходимые параметры квартиры")
    st.session_state.is_filled = st.button("Расчитать стоимость", type='primary', use_container_width=True)
    if st.session_state.is_filled:
        st.experimental_rerun()
else:
    st.subheader("Результат оценки")
    with st.spinner("Расчет стоимости..."):
        fields = {key: st.session_state[key] for key in ('build_year', 'num_room', 'floor')}
        total = 5400000
        details = {'build_year': 0.60, 'num_room': 0.30, 'floor': 0.10}
        st_pyecharts(build_price_title_chart(total=total), height=50)
        st_pyecharts(build_price_components_imact_chart(total=total, details=details), height=400)
    # import time
    # time.sleep(2)
    st.subheader("Динамика цены квартиры с указанными параметрами")
    with st.spinner("Построение тренда..."):
        price_flow = [
            dict(date=datetime(2023, 3, 3), price=5_200_000),
            dict(date=datetime(2023, 3, 5), price=5_300_000),
            dict(date=datetime(2023, 3, 7), price=5_400_000),
            dict(date=datetime(2023, 3, 9), price=5_250_000),
            dict(date=datetime(2023, 3, 11), price=5_450_000),
            dict(date=datetime(2023, 3, 13), price=5_400_000),
        ]
        st_pyecharts(build_price_dynamic_chart(price_flow=price_flow))
    # import time
    # time.sleep(2)
    st.subheader("Похожие предложения")
    with st.spinner("Подбор альтернатив..."):
        T = lambda impact, value: dict(impact=impact, originalValue=value)
        price_details = {k: T(v, fields[k]) for k, v in details.items()}
        target_offer = dict(details=price_details, price=total, address="Адрес X")
        similar_offers_details = [
            {'details': {'build_year': T(0.40, 1960), 'num_room': T(0.50, 3), 'floor': T(0.10, 5)}, 'price': 6_000_000, 'address': "Адрес 1"},
            {'details': {'build_year': T(0.55, 1993), 'num_room': T(0.40, 2), 'floor': T(0.05, 5)}, 'price': 4_850_000, 'address': "Адрес 2"},
            {'details': {'build_year': T(0.60, 2012), 'num_room': T(0.38, 1), 'floor': T(0.02, 10)}, 'price': 5_200_000, 'address': "Адрес 3"},
            {'details': {'build_year': T(0.58, 2009), 'num_room': T(0.37, 1), 'floor': T(0.05, 12)}, 'price': 5_250_000, 'address': "Адрес 4"},
        ]
        st_pyecharts(build_competitive_price_chart(
            target_offer=target_offer,
            similar_offers_details=similar_offers_details
        ), height='500px')
    # fig = None
    # st.plotly_chart(fig, theme=None, use_container_width=True)

st.header("Задействованные технологии")
st.markdown("""
<div style="width: 740; display: flex; align-items: center; justify-content: center; gap: 50px">
    <img src="https://s4-recruiting.cdn.greenhouse.io/external_greenhouse_job_boards/logos/400/515/800/original/logo-clickhouse.png?1634065357" height="100px">
    <img src="https://upload.wikimedia.org/wikipedia/commons/d/de/AirflowLogo.png" height="100px">
    <img src="https://d1.awsstatic.com/PAC/kuberneteslogo.eabc6359f48c8e30b7a138c18177f3fd39338e05.png" height="100px">
</div>
""", unsafe_allow_html=True)