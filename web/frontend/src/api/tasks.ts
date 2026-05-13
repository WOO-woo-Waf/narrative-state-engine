import { apiGet } from "./client";
import type { TasksResponse } from "../types/task";

export function getTasks(): Promise<TasksResponse> {
  return apiGet<TasksResponse>("/tasks");
}
