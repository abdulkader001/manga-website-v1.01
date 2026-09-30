export default function useAccountSync(enabled?: boolean) {
  return {
    isSyncing: false,
    syncNow: () => {},
  };
}
