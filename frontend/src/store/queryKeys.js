/**
 * TanStack Query cache key constants.
 * Used with @tanstack/react-query for deduplication, background polling,
 * and cache invalidation across the application.
 *
 * Specs: specs_frontend.md §4
 */

export const queryKeys = {
  /** Current inventory of assets. Polled during Discovery Phase. */
  assets: ['assets'],

  /** Global session flags: is_paused, is_deadlocked, status. */
  session: ['session_status'],

  /** Current points valuations for the active heir. */
  valuations: (heirId) => ['valuations', heirId],

  /** (Admin-only) Open heir help requests. */
  support: ['support_requests'],

  /** Calling Heir's own profile and verification status. */
  profile: ['heir_profile'],
};