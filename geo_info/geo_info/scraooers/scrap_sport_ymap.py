#%%
import asyncio
import json
import logging
import os
import re
from itertools import islice

import numpy as np 
import redis.asyncio as redis
from arsenic import get_session, browsers, services
from arsenic.constants import SelectorType
from arsenic.errors import NoSuchElement
from tqdm import tqdm


R = redis.Redis(host='localhost')


async def get_restaurants_info(longitude, latitude, width, height):
    service = services.Remote(os.getenv('SELENIUM_REMOTE_URL'))
    browser = browsers.Firefox()
    async with get_session(service, browser) as session:
        url = f"https://yandex.ru/maps/213/moscow/search/Спорт/?from=mapsapi&indoorLevel=1&ll={longitude},{latitude}&sll={longitude},{latitude}&sspn={width},{height}&z=16"
        await session.get(url)
        print(url)
        await asyncio.sleep(1)
        sidebar_selector = "div.scroll__container"
        last_scroll, current_scroll = -1, 0
        while current_scroll != last_scroll:
            last_scroll = current_scroll
            await session.execute_script(r"document.querySelector(arguments[0]).scroll(0,arguments[1]);", sidebar_selector, current_scroll + 1000)
            await asyncio.sleep(1)
            current_scroll = await session.execute_script(r"return document.querySelector(arguments[0]).scrollTop;", sidebar_selector)
            print(current_scroll)
            # print(current_scroll)

        for card in await session.get_elements("//div[@class='search-snippet-view__body _type_business']", SelectorType.xpath):
            try:
                info = {}
                info['id'] = card_id = await card.get_attribute("data-id")
                lon, lat = list(map(float, (await card.get_attribute("data-coordinates")).split(',')))
                base_xpath = f"//div[@data-id='{card_id}']"
                info['title'] = await (await card.get_element(f"{base_xpath}//div[@class='search-business-snippet-view__title']", SelectorType.xpath)).get_text()
                print(info['title'])
                info['categories'] = [re.search(r"category\/(\w+)\/", await a.get_attribute("href"))[1] for a in await card.get_elements(f"{base_xpath}//a[@class='search-business-snippet-view__category']", SelectorType.xpath)]
                try:
                    info['rating'] = float((await (await card.get_element(f"{base_xpath}//div[@class='business-rating-badge-view__rating']/span[last()]", SelectorType.xpath)).get_text()).replace(',', '.'))
                    info['mark_count'] = int(re.search(r"\d+", await (await card.get_element(f"{base_xpath}//div[@class='business-rating-with-text-view__count']/div", SelectorType.xpath)).get_text())[0])
                except NoSuchElement as e:
                    print(e)
                try:
                    price = await card.get_element(f"{base_xpath}//span[@class='search-business-snippet-subtitle-view__title']", SelectorType.xpath)
                    if price_desc_match := re.search(r"[-\d]+", await price.get_text()):
                        info['mean_price'] = np.mean(list(map(float, price_desc_match[0].split('-')))) if '-' in price_desc_match[0] else float(price_desc_match[0])
                except NoSuchElement as e:
                    print(e)
            except NoSuchElement:
                continue
            else:
                await R.geoadd(f"organization:sport", (lon, lat, json.dumps(info)))


async def main():
    arc_step = k = 0.013976927308961724
    r, phi = k, 0
    center = np.array([55.755865, 37.617520])
    path = []
    while r < 0.8:
        dphi = np.arcsin(arc_step / r)
        phi += dphi
        r = k * phi
        v = r*np.array([0.5*np.cos(phi), np.sin(phi)])
        lat, lon = center + v
        path.append([lat, lon])
    start = 1591
    for lat, lon in tqdm(path[start:], initial=start):
        await get_restaurants_info(lon, lat, k, 0.5*k)
        # break

if __name__ == '__main__':
    import arsenic
    arsenic.connection.log.info = lambda *args, **kwargs: ...
    asyncio.run(main())

#%%
# import pandas as pd
# import plotly.express as px
# px.set_mapbox_access_token("pk.eyJ1Ijoia2FyYXRhY2gxOTk4IiwiYSI6ImNsaHpwYTh6MTFlYmczZW1kMGVjdDVuY2kifQ.fz_w5oWeuSGZtnofe-iJTg")
# df = pd.DataFrame.from_records(np.array(path), columns=['lat', 'lon'])
# fig = px.scatter_mapbox(df, lat='lat', lon='lon')
# fig.show()