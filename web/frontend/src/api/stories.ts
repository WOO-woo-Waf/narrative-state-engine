import { apiGet } from "./client";
import type { StoriesResponse } from "../types/story";

export function getStories(): Promise<StoriesResponse> {
  return apiGet<StoriesResponse>("/stories");
}
