import { describe, it, expect } from "vitest";
import { parseSseStream, type SseEvent } from "../sse";

function streamFromChunks(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      }
      controller.close();
    },
  });
}

async function collect(chunks: (string | Uint8Array)[]): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of parseSseStream(streamFromChunks(chunks))) {
    events.push(event);
  }
  return events;
}

describe("lib/sse.ts - parseSseStream", () => {
  it("produce un evento por data: aunque lleguen fragmentados a mitad de línea", async () => {
    const events = await collect([
      'data: {"event":"analysis_started","seq":1}\n\n',
      'data: {"event":"step_started","seq":2',
      ',"step":"STRUCTURE"}\n\n',
      'data: {"event":"step_completed","seq":3}\n\n',
    ]);

    expect(events).toHaveLength(3);
    expect(events.map((event) => event.event)).toEqual([
      "analysis_started",
      "step_started",
      "step_completed",
    ]);
    expect(JSON.parse(events[1].data).step).toBe("STRUCTURE");
  });

  it("maneja trozos partidos a mitad de un carácter UTF-8", async () => {
    const text =
      'data: {"event":"analysis_started","seq":1,"symbol":"BTC/USDT","note":"café"}\n\n';
    const bytes = new TextEncoder().encode(text);
    const accentIndex = text.indexOf("é");
    const accentByteIndex = new TextEncoder().encode(text.slice(0, accentIndex)).length;
    const split = accentByteIndex + 1;

    const events = await collect([bytes.slice(0, split), bytes.slice(split)]);

    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("analysis_started");
    expect(JSON.parse(events[0].data).note).toBe("café");
  });

  it("ignora comentarios y líneas vacías", async () => {
    const events = await collect([
      ": comentario SSE\n",
      "\n",
      'data: {"event":"analysis_started","seq":1}\n\n',
      ": otro comentario\n",
      "\n",
      'data: {"event":"step_started","seq":2,"step":"STRUCTURE"}\n\n',
    ]);

    expect(events).toHaveLength(2);
    expect(events[0].event).toBe("analysis_started");
    expect(events[1].event).toBe("step_started");
  });

  it("rechaza un evento sin el discriminante event y lo nombra", async () => {
    await expect(collect(['data: {"seq":1,"symbol":"BTC/USDT"}\n\n'])).rejects.toThrow(
      /discriminante.*event/i,
    );
  });

  it("rechaza un evento con event desconocido y lo nombra", async () => {
    await expect(collect(['data: {"event":"unknown_event","seq":1}\n\n'])).rejects.toThrow(
      /desconocido.*unknown_event/i,
    );
  });

  it("rechaza un data: con JSON inválido", async () => {
    await expect(collect(["data: {no-es-json}\n\n"])).rejects.toThrow(/JSON inválido/i);
  });

  it("termina limpio al cerrar el stream", async () => {
    const events = await collect(['data: {"event":"analysis_started","seq":1}\n\n']);
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("analysis_started");
  });

  it("emite el último evento aunque el stream cierre sin la línea en blanco final", async () => {
    const events = await collect(['data: {"event":"analysis_started","seq":1}']);
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("analysis_started");
  });

  it("maneja múltiples eventos data: en un solo chunk", async () => {
    const events = await collect([
      'data: {"event":"analysis_started","seq":1}\n\ndata: {"event":"step_started","seq":2,"step":"STRUCTURE"}\n\n',
    ]);
    expect(events).toHaveLength(2);
    expect(events.map((event) => event.event)).toEqual([
      "analysis_started",
      "step_started",
    ]);
  });

  it("ignora las líneas id: y retry:", async () => {
    const events = await collect([
      'id: 123\nretry: 5000\ndata: {"event":"analysis_started","seq":1}\n\n',
    ]);
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("analysis_started");
  });

  it("admite finales de línea CRLF", async () => {
    const events = await collect(['data: {"event":"analysis_started","seq":1}\r\n\r\n']);
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("analysis_started");
    expect(JSON.parse(events[0].data).seq).toBe(1);
  });
});
