import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './Page/MainPage.js';
import reportWebVitals from './reportWebVitals';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import {HelpPage} from './Page/HelpPage';
import {AboutPage} from './Page/AboutPage';
import { InstanceDetailPage } from './Page/InstanceDetailPage.js';
import { LinkDetailPage } from './Page/LinkDetailPage.js';

class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error('OpenSN WebUI render error:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '2rem', fontSize: '16px' }}>
          页面渲染失败，请查看浏览器控制台日志或刷新后重试。
        </div>
      );
    }
    return this.props.children;
  }
}
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <RootErrorBoundary>
    <BrowserRouter>
      <Routes>
        <Route path="/help" element={<HelpPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/instance/:node_index/:instance_id" element={<InstanceDetailPage/>} />
        <Route path='/link/:node_index/:link_id' element={<LinkDetailPage />} />
        <Route path="/" element={<App />} />
      </Routes>
    </BrowserRouter>
  </RootErrorBoundary>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
