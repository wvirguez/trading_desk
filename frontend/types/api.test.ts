import { describe, expectTypeOf, it } from "vitest";
import type { components, paths } from "./api";

type OhlcvGet = paths["/api/v1/market/ohlcv"]["get"];
type OhlcvOk = OhlcvGet["responses"]["200"]["content"]["application/json"];

describe("tipos generados de la API", () => {
  it("GET /market/ohlcv devuelve un array de CandleSchema", () => {
    expectTypeOf<OhlcvOk>().toEqualTypeOf<components["schemas"]["CandleSchema"][]>();
  });

  it("los precios de CandleSchema son cadenas (D3)", () => {
    expectTypeOf<components["schemas"]["CandleSchema"]["open"]>().toEqualTypeOf<string>();
  });
});
