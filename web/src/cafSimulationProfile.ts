export type SimulationRecord = {
  ref: string;
  class_id: string | null;
  class_version: string | null;
  class_name: string;
  name: string;
  property_id: string;
  kind: "simulationProperty";
  native_type: string | null;
  attributes: Record<string, string> | null;
  old: string | null;
  value: string | null;
  editable: boolean;
  reason: string;
  enum_semantics_verified?: false;
  maximum_code?: number;
};
export type Profile = {
  format: "bms.caf-simulation-profile";
  version: 1 | 2;
  source_sha256: string;
  entries: SimulationRecord[];
};
export type Summary = {
  sha256: string;
  records: SimulationRecord[];
  counts: {
    total: number;
    editable: number;
    read_only: number;
    types?: Record<string, number>;
  };
  validation: string;
  profile_version?: 2;
};
export function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
export function signature(profile: Profile | null) {
  return stable(
    profile
      ? {
          version: profile.version,
          source_sha256: profile.source_sha256,
          values: profile.entries.map(({ ref, property_id, value }) => ({
            ref,
            property_id,
            value,
          })),
        }
      : [],
  );
}
const recordKey = (row: SimulationRecord) => stable([row.ref, row.property_id]);
const code = (text: any) =>
  typeof text === "string" &&
  /^(0|[1-9][0-9]{0,9})$/.test(text) &&
  Number(text) <= 4294967295;

export function admitSimulationSource(
  inventory: Summary,
  profile: Profile,
  sha: string,
  version: 1 | 2,
) {
  if (
    !inventory ||
    !profile ||
    !/^[a-f0-9]{64}$/.test(sha) ||
    inventory.sha256 !== sha ||
    (inventory.profile_version ?? 1) !== version ||
    profile.format !== "bms.caf-simulation-profile" ||
    profile.version !== version ||
    profile.source_sha256 !== sha ||
    !Array.isArray(profile.entries) ||
    !Array.isArray(inventory.records) ||
    profile.entries.length > 10000 ||
    stable(profile.entries) !== stable(inventory.records) ||
    new Blob([JSON.stringify(profile)]).size + 1024 > 2 * 1024 * 1024
  )
    throw new Error(
      "Saved simulation source/profile does not match the selected CAF, version or complete records.",
    );
  const seen = new Set<string>();
  for (const row of profile.entries) {
    if (
      !row ||
      typeof row !== "object" ||
      typeof row.ref !== "string" ||
      !row.ref ||
      typeof row.class_name !== "string" ||
      typeof row.name !== "string" ||
      ![row.class_id, row.class_version, row.native_type].every(
        (value) => value === null || typeof value === "string",
      ) ||
      typeof row.property_id !== "string" ||
      row.kind !== "simulationProperty" ||
      typeof row.editable !== "boolean" ||
      typeof row.reason !== "string" ||
      !(row.old === null || typeof row.old === "string") ||
      row.value !== row.old ||
      !(
        row.attributes === null ||
        (typeof row.attributes === "object" &&
          !Array.isArray(row.attributes) &&
          Object.values(row.attributes).every((v) => typeof v === "string"))
      ) ||
      seen.has(recordKey(row))
    )
      throw new Error(
        "Saved simulation source contains incomplete or conflicting native records.",
      );
    seen.add(recordKey(row));
    const base = [
      "ref",
      "class_id",
      "class_version",
      "class_name",
      "name",
      "property_id",
      "kind",
      "native_type",
      "attributes",
      "old",
      "value",
      "editable",
      "reason",
    ];
    const extra =
      row.native_type === "enum" && version === 2
        ? ["enum_semantics_verified", "maximum_code"]
        : [];
    if (
      Object.keys(row).sort().join() !== [...base, ...extra].sort().join() ||
      (extra.length &&
        (row.enum_semantics_verified !== false ||
          row.maximum_code !== 4294967295))
    )
      throw new Error(
        "Saved simulation metadata has an unknown shape or Enum authority claim.",
      );
    if (row.editable) {
      const float =
          row.native_type === "float" &&
          ["526", "527"].includes(row.class_id ?? ""),
        boolean =
          row.native_type === "boolean" &&
          row.class_id === "530" &&
          ["0", "1", "false", "true"].includes(row.old ?? ""),
        enumerated =
          version === 2 &&
          row.native_type === "enum" &&
          ["528", "529"].includes(row.class_id ?? "") &&
          code(row.old) &&
          row.attributes !== null &&
          Object.keys(row.attributes).every((k) => k === "set");
      if (
        row.class_version !== "1.0" ||
        row.property_id !== "3113" ||
        typeof row.old !== "string" ||
        !(float || boolean || enumerated) ||
        (!enumerated &&
          Object.keys(row.attributes ?? { unavailable: "" }).length)
      )
        throw new Error(
          "Saved simulation source claims an unsupported editable representation.",
        );
    }
  }
  const editable = profile.entries.filter((r) => r.editable).length;
  if (
    inventory.counts?.total !== profile.entries.length ||
    inventory.counts.editable !== editable ||
    inventory.counts.read_only !== profile.entries.length - editable ||
    typeof inventory.validation !== "string"
  )
    throw new Error(
      "Saved simulation source counts or scope differ from its records.",
    );
  return profile;
}

export function importProfile(value: unknown, original: Profile): Profile {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new Error("Choose a saved CAF simulation profile JSON object.");
  const next = value as Record<string, unknown>;
  if (
    stable(Object.keys(next).sort()) !==
      stable(["entries", "format", "source_sha256", "version"]) ||
    next.format !== original.format ||
    next.version !== original.version ||
    next.source_sha256 !== original.source_sha256 ||
    !Array.isArray(next.entries) ||
    next.entries.length !== original.entries.length
  )
    throw new Error(
      "Profile must match this exact CAF SHA-256, format, version and complete record count.",
    );
  const expected = new Map(
      original.entries.map((row) => [recordKey(row), row]),
    ),
    seen = new Set<string>(),
    values = new Map<string, string | null>();
  for (const candidate of next.entries) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate))
      throw new Error("Profile contains an invalid native record.");
    const row = candidate as SimulationRecord,
      key = recordKey(row),
      prior = expected.get(key);
    if (!prior || seen.has(key))
      throw new Error("Profile contains duplicate or unknown native records.");
    seen.add(key);
    const { value: replacement, ...guards } = row,
      { value: previous, ...expectedGuards } = prior;
    void previous;
    if (stable(guards) !== stable(expectedGuards))
      throw new Error(
        "Profile identity, native type or old-value guard changed.",
      );
    if (!prior.editable && replacement !== prior.old)
      throw new Error("Profile attempted to edit a read-only native record.");
    if (prior.editable && typeof replacement !== "string")
      throw new Error("Editable profile values must use native scalar text.");
    values.set(key, replacement);
  }
  return {
    ...original,
    entries: original.entries.map((row) => ({
      ...row,
      value: values.get(recordKey(row))!,
    })),
  };
}

export function carryLegacySimulation(
  legacy: Profile,
  current: Profile,
): Profile {
  if (
    legacy.version !== 1 ||
    current.version !== 2 ||
    legacy.source_sha256 !== current.source_sha256 ||
    legacy.entries.length !== current.entries.length
  )
    throw new Error(
      "Legacy simulation import requires the same exact CAF source.",
    );
  const old = new Map(legacy.entries.map((row) => [recordKey(row), row]));
  if (old.size !== legacy.entries.length)
    throw new Error("Legacy simulation profile contains duplicate records.");
  return {
    ...current,
    entries: current.entries.map((row) => {
      const prior = old.get(recordKey(row));
      if (
        !prior ||
        prior.old !== row.old ||
        prior.class_id !== row.class_id ||
        prior.native_type !== row.native_type ||
        prior.class_version !== row.class_version ||
        stable(prior.attributes) !== stable(row.attributes)
      )
        throw new Error(
          "Legacy simulation source metadata changed during adaptation.",
        );
      if (
        (!prior.editable && prior.value !== prior.old) ||
        (prior.editable &&
          !(
            typeof prior.value === "string" &&
            prior.class_version === "1.0" &&
            prior.property_id === "3113" &&
            ((prior.native_type === "float" &&
              ["526", "527"].includes(prior.class_id ?? "")) ||
              (prior.native_type === "boolean" && prior.class_id === "530"))
          ))
      )
        throw new Error(
          "Legacy simulation import cannot grant Enum or unknown-type edits.",
        );
      return { ...row, value: prior.editable ? prior.value : row.old };
    }),
  };
}
