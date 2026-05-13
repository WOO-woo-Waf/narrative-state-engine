import { apiGet } from "./client";

export type HealthResponse = {
  status?: string;
  database?: {
    configured?: boolean;
    ok?: boolean;
    message?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
};

export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/health");
}
