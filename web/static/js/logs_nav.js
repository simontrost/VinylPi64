/* Show only new warning/error messages; seen state is local to this browser. */
(() => {
    const badge = document.getElementById('logsUnreadBadge');
    if (!badge) return;
    const key = 'vinylpi.logs.seen';
    const isLogPage = location.pathname === '/logs.html';
    const seen = () => {
        try { return Math.max(0, Number(localStorage.getItem(key)) || 0); }
        catch { return 0; }
    };
    const store = id => {
        try { localStorage.setItem(key, String(Math.max(id, seen()))); }
        catch { /* Storage can be disabled. */ }
    };
    async function check() {
        if (document.hidden) return;
        try {
            const response = await fetch(`/api/logs/summary?since=${seen()}`, { cache: 'no-store' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const summary = await response.json();
            if (isLogPage) {
                // Opening diagnostics acknowledges existing notifications.
                store(summary.latest_id);
                badge.hidden = true;
                return;
            }
            const count = Math.max(0, summary.unread || 0);
            badge.hidden = count === 0;
            badge.textContent = count > 99 ? '99+' : String(count);
            badge.setAttribute('aria-label', `${count} new warnings or errors`);
        } catch {
            badge.hidden = true;
        }
    }
    window.vinylpiMarkLogsSeen = store;
    check();
    setInterval(check, 12000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
})();
