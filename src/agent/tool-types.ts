export type ToolHandler = (args: unknown) => Promise<unknown>;

/** OpenAI Chat Completions `tools[]` item shape (function spec). */
export type ToolSpec = {
  type: "function";
  function: {
    name: string;
    description?: string;
    parameters?: Record<string, unknown>;
  };
};

export type ToolDef = { spec: ToolSpec; handler: ToolHandler };
