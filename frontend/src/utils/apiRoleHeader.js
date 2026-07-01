/**
 * installApiRoleHeader — tags every same-origin /api request with which
 * console is calling it, so the backend can tell an Admin session cookie
 * apart from a Heir session cookie when a single browser holds both at
 * once (e.g. one tab on /admin, another on /dashboard/invite/login).
 *
 * The backend (`get_current_user` in backend/app/auth.py) reads this as
 * the `X-Estate-Role` header to pick which of the two role-scoped
 * cookies (estate_admin_session / estate_heir_session) applies to a
 * given request. Without it, both roles would keep silently evicting
 * each other from the shared cookie jar.
 *
 * Role is derived from the current route rather than in-memory auth
 * state, since a route is unambiguous the instant a request fires
 * (including the very first "am I logged in?" check on page load,
 * before any role is known yet).
 */
export function installApiRoleHeader() {
  if (typeof window === 'undefined' || window.__estateRoleHeaderInstalled) return;
  window.__estateRoleHeaderInstalled = true;

  const originalFetch = window.fetch.bind(window);

  window.fetch = (input, init) => {
    const url = typeof input === 'string' || input instanceof URL ? String(input) : input?.url;

    if (url && url.startsWith('/api/')) {
      const role = window.location.pathname.startsWith('/admin') ? 'ADMIN' : 'HEIR';
      const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
      headers.set('X-Estate-Role', role);
      return originalFetch(input, { ...init, headers });
    }

    return originalFetch(input, init);
  };
}
