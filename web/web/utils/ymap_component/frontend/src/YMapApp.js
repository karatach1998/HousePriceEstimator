import _ from 'underscore';
import { useState, useEffect } from 'react';
import { YMaps, Map, Placemark, ZoomControl, GeolocationControl } from '@pbe/react-yandex-maps';
import { Streamlit } from 'streamlit-component-lib';
// import { useRenderData } from 'streamlit-component-lib-react-hooks';

// const DEFAULT_POS = {latitude: 55.75, longitude: 37.5};
const DEFAULT_POS = {latitude:55.769359, longitude:37.588234};

const YMapApp = () => {
  const [renderData, setRenderData] = useState();
  const {label, initial: initialPos} = renderData?.args ?? {};
  const [pos, setPos] = useState(initialPos ?? DEFAULT_POS);

  const mapState = { center: _.values(pos), zoom: 9 };

  useEffect(() => {
    const onRenderEvent = (event) => {
      setRenderData(event.detail);
    };

    Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRenderEvent);
    Streamlit.setComponentReady();
    Streamlit.setFrameHeight(600);

    return () => {
      Streamlit.events.removeEventListener(Streamlit.RENDER_EVENT, onRenderEvent);
    }
  }, []);

  useEffect(() => {
    console.log(pos);
    Streamlit.setComponentValue(pos);
  }, [pos]);

  return (
      <YMaps>
        {label != null && (
          <label>{label}</label>
        )}
        <Map defaultState={mapState} width={"100%"} height={"auto"} options={{autoFitToViewport: true}} onClick={e => setPos(_.object(['latitude', 'longitude'], e._sourceEvent.originalEvent.coords))}>
          <GeolocationControl />
          <ZoomControl />
          <Placemark geometry={_.values(pos)} properties={{balloonContent: "Адрес"}} options={{preset: 'islands#blueHomeIcon'}} />
        </Map>
      </YMaps>
  );
}

export default YMapApp;