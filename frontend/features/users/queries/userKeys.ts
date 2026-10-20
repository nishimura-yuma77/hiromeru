export const userKeys = {
  lists: ["admin-users", "list"] as const,
  list: (page: number) => [...userKeys.lists, page] as const,
};
