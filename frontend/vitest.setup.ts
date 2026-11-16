import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import "./lib/__tests__/ws-mock";

afterEach(() => {
  cleanup();
});