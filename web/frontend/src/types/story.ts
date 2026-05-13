export type Story = {
  story_id: string;
  title?: string;
  status?: string;
  updated_at?: string;
};

export type StoriesResponse = {
  stories: Story[];
  default_story_id?: string;
};
