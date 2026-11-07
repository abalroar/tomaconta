import React, {useState} from 'react';
import {BASE} from './data.js';
import './sections.css';

export const APP_NAVIGATION = [
  ['institutions', 'Instituições'],
  ['sfn', 'Sistema financeiro'],
  ['imob', 'Mercado imobiliário'],
  ['payments', 'Pagamentos'],
  ['update', 'Atualizar base'],
];

export default function AppShell({page, onNavigate, header, children}) {
  const [menuOpen, setMenuOpen] = useState(false);
  function navigate(event, destination) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    setMenuOpen(false);
    onNavigate(destination);
  }
  return <div className="tc-workspace">
    <header className="tc-app-nav">
      <a className="tc-app-wordmark" href={BASE} onClick={event => navigate(event, 'overview')}>Toma Conta.</a>
      <button className="tc-app-menu" type="button" aria-expanded={menuOpen} aria-controls="tc-app-navigation" onClick={() => setMenuOpen(!menuOpen)}>Menu</button>
      <nav id="tc-app-navigation" className={menuOpen ? 'is-open' : ''} aria-label="Navegação principal">
        {APP_NAVIGATION.map(([id, label]) => <a key={id} href={`${BASE}?view=${id}`} aria-current={page === id ? 'page' : undefined} onClick={event => navigate(event, id)}>{label}</a>)}
      </nav>
    </header>
    {header}
    <main className="tc-workspace-main">{children}</main>
    <footer className="tc-app-footer"><span>Toma Conta</span><a href="/">matheusprat.es</a></footer>
  </div>;
}
