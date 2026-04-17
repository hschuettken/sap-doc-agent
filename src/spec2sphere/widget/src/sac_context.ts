export interface SacContext {
  user: string;
  hints: Record<string, unknown>;
}

export async function resolveContext(
  fallback?: { user?: string },
): Promise<SacContext> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const g: any = globalThis;
    const sacUser: string =
      g?.sap?.bi?.designer?.context?.user?.email ||
      g?.sap?.bi?.story?.context?.user?.email ||
      fallback?.user ||
      '_anonymous';
    const storyId: string | undefined =
      g?.sap?.bi?.designer?.currentStoryId ||
      g?.sap?.bi?.story?.id;
    return {
      user: sacUser,
      hints: storyId ? { story_id: storyId } : {},
    };
  } catch {
    return { user: fallback?.user ?? '_anonymous', hints: {} };
  }
}
