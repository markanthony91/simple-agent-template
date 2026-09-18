// Public verifier only, never a bearer credential. Empty = fail closed.
// Populate the verifier and model allowlist when deploying this dedicated bridge.
export const BRIDGE_CONFIG = { token_sha256: "", models: [] as string[] };
