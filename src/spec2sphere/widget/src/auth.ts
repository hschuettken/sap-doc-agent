/**
 * Lightweight JWT payload decoder for the SAC widget.
 *
 * The widget does NOT verify the signature — that is the server's job.
 * We only decode the claims to decide which UI elements to show (e.g.
 * the author-only admin chip). An expired or tampered token will be
 * rejected by the live adapter on the next API call.
 */

export interface JwtPayload {
  role?: string;
  user_id?: string;
  customer?: string;
  exp?: number;
}

/**
 * Decode the payload segment of a JWT without verifying the signature.
 * Returns null if the token is missing, malformed, or unparseable.
 */
export function decodeJwtPayload(token: string | null): JwtPayload | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    // base64url → base64 → decode
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    // Pad to a multiple of 4
    const padded = b64 + '=='.slice((b64.length + 2) % 4);
    const raw = atob(padded);
    return JSON.parse(raw) as JwtPayload;
  } catch {
    return null;
  }
}

/**
 * Returns true when the token carries the 'author' role claim.
 * False for viewer, widget, null, or malformed tokens.
 */
export function isAuthor(token: string | null): boolean {
  return decodeJwtPayload(token)?.role === 'author';
}
