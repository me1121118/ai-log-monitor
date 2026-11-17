import { mountErFlow } from './ErFlowApp.jsx';

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mountErFlow);
} else {
  mountErFlow();
}
