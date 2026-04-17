import { describe, it, expect } from 'vitest';
import { decodeJwtPayload, isAuthor } from '../src/auth';

/**
 * Build a minimal (unsigned) JWT for testing the payload decoder.
 * We only need the header.payload.signature structure — the widget
 * never verifies the signature, so we can use a dummy sig.
 */
function makeTestToken(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  const body = btoa(JSON.stringify(payload))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  return `${header}.${body}.fakesignature`;
}

describe('decodeJwtPayload', () => {
  it('returns payload claims for a well-formed token', () => {
    const token = makeTestToken({
      role: 'author',
      user_id: 'alice@example.com',
      customer: 'acme',
      exp: 9999999999,
    });
    const payload = decodeJwtPayload(token);
    expect(payload).not.toBeNull();
    expect(payload?.role).toBe('author');
    expect(payload?.user_id).toBe('alice@example.com');
    expect(payload?.customer).toBe('acme');
  });

  it('returns null for null input', () => {
    expect(decodeJwtPayload(null)).toBeNull();
  });

  it('returns null for an empty string', () => {
    expect(decodeJwtPayload('')).toBeNull();
  });

  it('returns null for a token with wrong number of segments', () => {
    expect(decodeJwtPayload('only.two')).toBeNull();
    expect(decodeJwtPayload('one')).toBeNull();
  });

  it('returns null when the payload segment is not valid base64/JSON', () => {
    expect(decodeJwtPayload('header.!!!invalid!!!.sig')).toBeNull();
  });

  it('ignores expiry — widget never enforces exp (server rejects)', () => {
    const expired = makeTestToken({
      role: 'viewer',
      user_id: 'bob',
      customer: 'test',
      exp: 1,  // in the past
    });
    const payload = decodeJwtPayload(expired);
    // We still decode it; exp=1 is just a number
    expect(payload?.role).toBe('viewer');
  });
});

describe('isAuthor', () => {
  it('returns true for a token with role=author', () => {
    const token = makeTestToken({ role: 'author', user_id: 'alice', customer: 'test', exp: 9999999999 });
    expect(isAuthor(token)).toBe(true);
  });

  it('returns false for a token with role=viewer', () => {
    const token = makeTestToken({ role: 'viewer', user_id: 'bob', customer: 'test', exp: 9999999999 });
    expect(isAuthor(token)).toBe(false);
  });

  it('returns false for a token with role=widget', () => {
    const token = makeTestToken({ role: 'widget', user_id: 'widget', customer: 'test', exp: 9999999999 });
    expect(isAuthor(token)).toBe(false);
  });

  it('returns false for null', () => {
    expect(isAuthor(null)).toBe(false);
  });

  it('returns false for a malformed token', () => {
    expect(isAuthor('not-a-jwt')).toBe(false);
  });
});
