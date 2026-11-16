export interface SseEvent {
  event: string;
  data: string;
}

const VALID_EVENTS = new Set([
  "analysis_started",
  "step_started",
  "step_completed",
  "step_failed",
  "analysis_completed",
  "analysis_failed",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function eventNameFromData(data: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    throw new Error("Evento SSE con JSON inválido");
  }

  if (!isRecord(parsed) || typeof parsed.event !== "string" || parsed.event.length === 0) {
    throw new Error("Evento SSE sin el discriminante 'event'");
  }

  if (!VALID_EVENTS.has(parsed.event)) {
    throw new Error(`Evento SSE desconocido: ${parsed.event}`);
  }

  return parsed.event;
}

export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent, void, unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let dataLines: string[] = [];

  function dispatch(): SseEvent | null {
    if (dataLines.length === 0) return null;
    const data = dataLines.join("\n");
    dataLines = [];
    return { event: eventNameFromData(data), data };
  }

  function consumeLine(line: string): SseEvent | null {
    if (line.endsWith("\r")) {
      line = line.slice(0, -1);
    }

    if (line.length === 0) {
      return dispatch();
    }

    if (line.startsWith(":")) {
      return null;
    }

    if (line === "data") {
      return null;
    }

    if (line.startsWith("data:")) {
      let value = line.slice(5);
      if (value.startsWith(" ")) {
        value = value.slice(1);
      }
      if (value.length > 0) {
        dataLines.push(value);
      }
      return null;
    }

    return null;
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let newlineIndex: number;
      while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 1);
        const event = consumeLine(line);
        if (event) {
          yield event;
        }
      }
    }

    buffer += decoder.decode();
    if (buffer.length > 0) {
      const event = consumeLine(buffer);
      if (event) {
        yield event;
      }
    }

    const finalEvent = dispatch();
    if (finalEvent) {
      yield finalEvent;
    }
  } finally {
    reader.releaseLock();
  }
}
