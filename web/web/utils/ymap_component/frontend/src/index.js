import React from 'react';
import ReactDOM from 'react-dom';
// import { StreamlitProvider } from 'streamlit-component-lib-react-hooks';
import YMapApp from './YMapApp';

ReactDOM.render(
  <React.StrictMode>
    {/* <StreamlitProvider> */}
      <YMapApp />
    {/* </StreamlitProvider> */}
  </React.StrictMode>,
  document.getElementById('root')
);
