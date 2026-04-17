export interface TelemetryEvent {
  event: string;
  enhancement_id?: string;
  user?: string;
  [key: string]: unknown;
}

export function postTelemetry(apiBase: string, event: TelemetryEvent): void {
  try {
    fetch(`${apiBase}/v1/telemetry`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(event),
      keepalive: true,
    }).catch(() => {
      // fire-and-forget; ignore errors
    });
  } catch {
    // never throw from telemetry
  }
}
