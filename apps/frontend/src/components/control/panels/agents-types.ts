export interface AgentIdentity {
  name?: string;
  theme?: string;
  emoji?: string;
  avatar?: string;
}

export interface AgentEntry {
  id: string;
  name?: string;
  identity?: AgentIdentity;
  model?: string;
}

export interface ModelCatalogEntry {
  alias?: string;
}

export interface ConfigSnapshot {
  path: string;
  exists: boolean;
  raw: string | null;
  config: ConfigInner;
  hash?: string;
  valid: boolean;
}

export interface AgentConfigEntry {
  id: string;
  model?: string | { primary?: string; fallbacks?: string[] };
  tools?: { profile?: string; alsoAllow?: string[]; deny?: string[] };
  [key: string]: unknown;
}

export interface ConfigInner {
  agents?: {
    defaults?: {
      models?: Record<string, ModelCatalogEntry>;
      model?: string | { primary?: string };
    };
    list?: AgentConfigEntry[];
  };
  tools?: { profile?: string; allow?: string[] };
  [key: string]: unknown;
}

export interface AgentsListResponse {
  defaultId?: string;
  mainKey?: string;
  scope?: string;
  agents?: AgentEntry[];
}

export interface AgentFileEntry {
  name: string;
  path: string;
  missing: boolean;
  size?: number;
  updatedAtMs?: number;
}

export interface AgentFilesResponse {
  agentId: string;
  workspace: string;
  files: AgentFileEntry[];
}

export interface AgentFileContent {
  agentId: string;
  file: AgentFileEntry & { content?: string };
}

export interface ToolEntry {
  name: string;
  id?: string;
  label?: string;
  description?: string;
  profile?: string;
  category?: string;
  source?: "core" | "plugin";
  pluginId?: string;
  optional?: boolean;
  defaultProfiles?: string[];
  [key: string]: unknown;
}

export interface ToolCatalogProfile { id: string; label: string }
export interface ToolCatalogGroup { id: string; label: string; source?: "core" | "plugin"; tools: ToolEntry[] }

export interface ToolsCatalogResponse {
  agentId?: string;
  profiles?: ToolCatalogProfile[] | Record<string, unknown>;
  groups?: ToolCatalogGroup[];
  tools?: ToolEntry[];
  [key: string]: unknown;
}
