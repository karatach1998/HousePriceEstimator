import re
import os
import json
import asyncio
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import geopy
import httpx
from arsenic import get_session, browsers, services, errors
from arsenic.session import Element, Session
from arsenic.constants import SelectorType
from celery import chain, Celery
from clickhouse_driver import Client as ClickHouseClient


CURRENCY_SYMBOL_TO_NAME = {
    "₽": "RUB",
    "€": "EUR",
    "$": "USD",
}
SVG_DATA_HEAD_TO_TRANSPORT = {
    'M10': 'пешком',
    'M14': 'на транспорте',
}
UNDERGROUND_COLOR_TO_LINE = {
    "#CF0000": "1",
    "#00701A": "2",
    "#03238B": "3",
    "#009BD5": "4",
    "#00701A": "5",
    "#FF7F00": "6",
    "#94007C": "7",
    "#FFCD1E": "8",
    "#FFDF00": "8А",
    "#A2A5B5": "9",
    "#8AD02A": "10",
    "#78C7C9": "11",
    "#BAC8E8": "12",
    "#0072B9": "13",
    "#FFC8C8": "14",
    "#D68AB1": "15",
}
INT_REGEX = re.compile(r"\d+")
FLOAT_REGEX = re.compile(r"\d+(\.\d+)?")
NUM_ROOMS_REGEX = re.compile(r"^(\d+|\w+)")
DEBUG = False


def parse_int(s):
    m = INT_REGEX.search(s)
    return int(m.group()) if m is not None else None


def parse_float(s):
    m = FLOAT_REGEX.search(s)
    if DEBUG: print(s)
    if DEBUG: print(m)
    return float(m.group()) if m is not None else None


celeryapp = Celery('cian_scrapper.main')
celeryapp.config_from_object(os.environ)


async def collect_cian_sale_links():
    url = "https://www.cian.ru/cat.php?deal_type=sale&engine_version=2&offer_type=flat&p={p}&region=1"
    process_sale = chain(get_cian_sale_info.s() | populate_with_area_info.s(), publish_result.s(os.getenv('SCRAPPER_RESULTS_TABLE')))
    total_sales = None
    sales_scrapped = 0
    page_index = 1
    service = services.Remote(os.getenv('SELENIUM_REMOTE_URL'))
    browser = browsers.Firefox()
    async with get_session(service, browser) as session:
        while total_sales is None or sales_scrapped < total_sales:
            await session.get(url.format(p=page_index))
            if total_sales is None:
                if search_summary := await (await session.get_element("//div[@data-name='SummaryHeader']/h5", SelectorType.xpath)).get_text():
                    total_sales = parse_int(search_summary.replace(' ', ''))
            elements = await session.get_elements("//article[@data-name='CardComponent']//div[@data-name='LinkArea']/a", SelectorType.xpath)
            for el in elements:
                print(await el.get_attribute('href'))
                process_sale.delay(await el.get_attribute('href'))
            break


@celeryapp.task
def publish_result(result, table_name):
    client = ClickHouseClient(
        host=os.getenv('CLICKHOUSE_HOST', "clickhouse"), 
        user=os.getenv('CLICKHOUSE_USER', "default"), 
        password=os.getenv('CLICKHOUSE_PASSWORD', "password"), 
    )
    result['coords'] = tuple(result['coords'][key] for key in ('latitude', 'longitude'))
    client.execute(
        f"INSERT INTO {table_name} ({','.join(result.keys())}) VALUES",
        [result],
        settings=dict(input_format_null_as_default=True)
    )


async def check_element(session_or_element: Session | Element, sel: str, sel_type: SelectorType) -> Element | None:
    try:
        return await session_or_element.get_element(sel, sel_type)
    except errors.NoSuchElement:
        return None


async def get_element_text(session_or_element: Session | Element, sel: str, sel_type: SelectorType) -> str | None:
    try:
        el = await session_or_element.get_element(sel, sel_type)
        return await el.get_text()
    except errors.NoSuchElement:
        return None


async def get_element_attribute(session_or_element, sel, sel_type, attr_name) -> str | None:
    try:
        el = await session_or_element.get_element(sel, sel_type)
        return await el.get_attribute(attr_name)
    except errors.NoSuchElement:
        return None


async def get_following_sibling_desc(session, *queries, converter=None):
    e = next(filter(bool, [await get_element_text(session, f"//*[text()='{q}']/following::*", SelectorType.xpath) for q in queries]), None)
    return (converter(e) if converter is not None else e) if e is not None else None


async def _get_cian_sale_info(sale_url):
    service = services.Remote(os.getenv('SELENIUM_REMOTE_URL'))
    browser = browsers.Firefox()
    result = None
    async with get_session(service, browser) as session:
        await session.get(sale_url)
        print(await session.get_element("title", SelectorType.tag_name))
        sale_id = int(re.search(r"\/(?P<sale_id>\d+)\/", sale_url)['sale_id'])
        price_str = (
            await get_element_text(session, "//span[@itemprop='price']", SelectorType.xpath) or
            await get_element_text(session, "//div[@data-name='PriceInfo']//span", SelectorType.xpath)
        )
        price_sep = re.search(r"\s", price_str[::-1]).group(0)
        price, _, price_currency = price_str.rpartition(price_sep)
        # print(price_str, ord(price_sep))
        price = int(re.search(r"\d+", price.replace(" ", "")).group())
        price_currency = CURRENCY_SYMBOL_TO_NAME.get(price_currency, price_currency)

        address = await get_element_attribute(session, "//div[@data-name='Geo']/span[@itemprop='name']", SelectorType.xpath, "content")
        try:
            map_desc_href = await (await session.get_element("//section[@data-name='NewbuildingMapWrapper']//a[@target='_blank' or @target='_self']", SelectorType.xpath)).get_attribute('href')
            latitude, longitude = list(map(float, parse_qs(urlparse(map_desc_href).query)["center"][0].split(',')))
        except:
            inline_script = await (await session.get_element("//body/script[@type='text/javascript'][contains(@text, 'coordinates')]")).get_text()
            m = json.loads(re.search(r'\"coordinates\":(\{["\w\d\.\,\:]+\})', inline_script)[1])
            # geopy_location = geopy.geocoders.Nominatim(user_agent="HousePriceEstimator").geocode(address)
            latitude, longitude = float(m["lat"]), float(m["lng"])
        finally:
            geopy_location = geopy.geocoders.Nominatim(user_agent="HousePriceEstimator").reverse((latitude, longitude))
        # print(driver.find_element(By.XPATH, "//*[@data-name='UndergroundIcon']/ancestor::li").get_attribute('innerHTML'))
        # global DEBUG
        # DEBUG = True
        # get_following_sibling_desc(driver, "Общая площадь", converter=parse_float)
        # DEBUG = False
        result =  dict(
            sale_id=sale_id,
            timestamp=int(datetime.now().timestamp()),
            coords=dict(latitude=latitude, longitude=longitude),
            address=address,
            district=geopy_location.raw['address']['suburb'],
            num_room=m[1] if (m := NUM_ROOMS_REGEX.search(await get_element_text(session, "//div[@data-name='OfferTitleNew']/h1", SelectorType.xpath))) else None,
            price=price,
            price_currency=price_currency,
            # undergrounds=sorted((
            #     dict(
            #         line=UNDERGROUND_COLOR_TO_LINE.get(await get_element_attribute(li, ".//*[@data-name='UndergroundIcon']", SelectorType.xpath, "fill")),
            #         station_name=await get_element_text(li, "a", SelectorType.tag_name),
            #         distance_in_min=parse_int(await get_element_text(li, "span", SelectorType.tag_name)),
            #         distance_in_min_transport=(
            #             int(
            #                 (await path.get_attribute("d"))[:3]
            #                 if (path := await check_element(span, "path", SelectorType.tag_name))
            #                 else (await span.get_text()).split(". ")[-1]
            #             )
            #             if (span := await check_element(li, "span", SelectorType.tag_name))
            #             else None
            #         )
            #     )
            #     for li in await session.get_elements("//*[@data-name='UndergroundIcon']/ancestor::li", SelectorType.xpath)
            #     if await get_element_attribute(li, ".//*[@data-name='UndergroundIcon']", SelectorType.xpath, "fill") in UNDERGROUND_COLOR_TO_LINE
            # ), key=lambda u: (u['distance_in_min_transport'] or 0) * 1000 + (u['distance_in_min'] or 0))[:2],
            apartment_type=await get_following_sibling_desc(session, "Тип жилья"),
            building_type=await get_following_sibling_desc(session, "Тип дома"),
            decorating=await get_following_sibling_desc(session, "Отделка", "Ремонт"),
            parking=await get_following_sibling_desc(session, "Парковка"),
            full_sq=await get_following_sibling_desc(session, "Общая площадь", converter=parse_float),
            life_sq=await get_following_sibling_desc(session, "Жилая площадь", converter=parse_float),
            kitch_sq=await get_following_sibling_desc(session, "Площадь кухни", converter=parse_float),
            height=await get_following_sibling_desc(session, "Высота потолков", converter=parse_float),
            floor=await get_following_sibling_desc(session, "Этаж", converter=lambda x: parse_int(x.split()[0])),
            max_floor=await get_following_sibling_desc(session, "Этаж", converter=lambda x: parse_int(x.split()[-1])),
            build_year=await get_following_sibling_desc(session, "Год сдачи", "Год постройки", converter=parse_int),
        )
    # print(result)
    return result


@celeryapp.task
def get_cian_sale_info(sale_url):
    return asyncio.get_event_loop().run_until_complete(_get_cian_sale_info(sale_url))


async def _populate_with_area_info(result):
    geoinfo_base_url = os.getenv("GEOINFO_BASE_URL")
    async with httpx.AsyncClient() as client:
        geoinfo_resp = await client.get(f"{geoinfo_base_url}/describe_area", params=result['coords'])
        result.update(geoinfo_resp.json())
    return result


@celeryapp.task
def populate_with_area_info(result):
    return asyncio.get_event_loop().run_until_complete(_populate_with_area_info(result))


if __name__ == '__main__':
    asyncio.run(collect_cian_sale_links())
    # asyncio.run(get_cian_sale_info("https://www.cian.ru/sale/flat/276096417/"))