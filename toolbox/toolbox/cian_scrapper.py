import re
import os
import json
import asyncio
from functools import cached_property

import aio_pika
from arsenic import get_session, browsers, services, errors
from arsenic.session import Element, Session
from arsenic.constants import SelectorType
from celery import Celery, Task
from celery.signals import worker_init, worker_shutting_down


CURRENCY_SYMBOL_TO_NAME = {
    "₽": "RUB",
    "€": "EUR",
    "$": "USD",
}
SVG_DATA_HEAD_TO_TRANSPORT = {
    'M10': 'пешком',
    'M14': 'на транспорте',
}
INT_REGEX = re.compile(r"\d+")
FLOAT_REGEX = re.compile(r"\d+(\.\d+)?")
DEBUG = False


def parse_int(s):
    m = INT_REGEX.search(s)
    return int(m.group()) if m is not None else None


def parse_float(s):
    m = FLOAT_REGEX.search(s)
    if DEBUG: print(s)
    if DEBUG: print(m)
    return float(m.group()) if m is not None else None


celeryapp = Celery('toolbox.cian_scrapper')
celeryapp.config_from_object(os.environ)


async def get_cian_sale_links():
    url = "https://www.cian.ru/cat.php?deal_type=sale&engine_version=2&offer_type=flat&p={p}&region=1"
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
                get_cian_sale_info.delay(await el.get_attribute('href'), link=publish_result.s(os.getenv('SCRAPPER_RESULTS_QUEUE')))
            break


class PikaTask(Task):
    def before_bind(self, app):


@celeryapp.task(base=PikaTask, bind=True)
async def publish_result(result, queue_name):
    print(result, queue_name)
    connection = await aio_pika.connect_robust(
        os.environ('BROKER_URL'), 
    )
    async with connection:
        channel = await connection.channel()
        await channel.default_exchange.publish(
            aio_pika.Message(body=json.dumps(result)),
            routing_key=queue_name,
        )
        await connection.close()


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


@celeryapp.task
# @profile
async def get_cian_sale_info(sale_url):
        service = services.Remote(os.getenv('SELENIUM_REMOTE_URL'))
        browser = browsers.Firefox()
        result = None
        async with get_session(service, browser) as session:
            await session.get(sale_url)
            print(await session.get_element("title", SelectorType.tag_name))
            sale_id = re.search(r"\/(?P<sale_id>\d+)\/", sale_url)['sale_id']
            price_str = (
                await get_element_text(session, "//span[@itemprop='price']", SelectorType.xpath) or
                await get_element_text(session, "//div[@data-name='PriceInfo']//span", SelectorType.xpath)
            )
            price_sep = re.search(r"\s", price_str[::-1]).group(0)
            price, _, price_currency = price_str.rpartition(price_sep)
            # print(price_str, ord(price_sep))
            price = int(re.search(r"\d+", price.replace(" ", "")).group())
            price_currency = CURRENCY_SYMBOL_TO_NAME.get(price_currency, price_currency)
            # print(driver.find_element(By.XPATH, "//*[@data-name='UndergroundIcon']/ancestor::li").get_attribute('innerHTML'))
            # global DEBUG
            # DEBUG = True
            # get_following_sibling_desc(driver, "Общая площадь", converter=parse_float)
            # DEBUG = False
            result =  dict(
                sale_id=sale_id,
                num_room=await get_element_text(session, "//div[@data-name='OfferTitleNew']/h1", SelectorType.xpath),
                price=price,
                price_currency=price_currency,
                address=await get_element_attribute(session, "//div[@data-name='Geo']/span[@itemprop='name']", SelectorType.xpath, "content"),
                undergrounds=[
                    dict(
                        branch_color=await get_element_attribute(li, ".//*[@data-name='UndergroundIcon']", SelectorType.xpath, "fill"),
                        station_name=await get_element_text(li, "a", SelectorType.tag_name),
                        distance_in_min=parse_int(await get_element_text(li, "span", SelectorType.tag_name)),
                        distance_in_min_transport=(
                            (
                                (await path.get_attribute("d"))[:3]
                                if (path := await check_element(span, "path", SelectorType.tag_name))
                                else (await span.get_text()).split(". ")[-1]
                           )
                            if (span := await check_element(li, "span", SelectorType.tag_name))
                            else None
                        )
                    )
                    for li in await session.get_elements("//*[@data-name='UndergroundIcon']/ancestor::li", SelectorType.xpath)
                ],
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
        print(result)
        return result


async def run_cian_link_collection():
    print('RUN')
    await get_cian_sale_links()
        

if __name__ == '__main__':
    asyncio.run(run_cian_link_collection())
    # asyncio.run(get_cian_sale_info("https://www.cian.ru/sale/flat/276096419/"))