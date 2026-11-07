/** Native tab buttons share the same keyboard behavior across both analysis levels. */
export function tabNavigation(event){
  if(event.altKey||event.ctrlKey||event.metaKey||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const buttons=[...event.currentTarget.closest('[role="tablist"]').querySelectorAll('[role="tab"]')].filter(button=>!button.disabled),at=buttons.indexOf(event.currentTarget);
  const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(at+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
  event.preventDefault();buttons[next]?.focus();buttons[next]?.click();
}
