export type Polarity = "normal" | "reverse";
export type ContactAction = "add" | "move" | "polarity";
export type ContactForm = {
  object: string;
  slot: string;
  instance: string;
  name: string;
  contactAction: ContactAction;
  polarity: Polarity;
};
type Contact = {
  object: string;
  name: string;
  slot: number;
  polarity: Polarity | null;
  active_text: string;
  inactive_text: string;
  unavailable_reason: string | null;
};
export type ContactCatalog = { contacts: Contact[]; available_slots: number[] };

export function selectContact(
  catalog: ContactCatalog,
  action: ContactAction,
  previous?: string,
): Partial<ContactForm> {
  const available = catalog.contacts.filter((c) => !c.unavailable_reason);
  const c = available.find((c) => c.object === previous) || available[0];
  return {
    contactAction: action,
    object: action === "add" ? "" : c?.object || "",
    slot: String(
      action === "polarity"
        ? (c?.slot ?? "")
        : (catalog.available_slots[0] ?? ""),
    ),
    polarity:
      action === "polarity" && c?.polarity === "normal" ? "reverse" : "normal",
  };
}

export function contactProposal(catalog: ContactCatalog, f: ContactForm) {
  const c = catalog.contacts.find(
    (p) => p.object === f.object && !p.unavailable_reason,
  );
  const add = f.contactAction === "add";
  const slot = Number(f.slot);
  if (!add && !c) throw Error("Select a configured dry contact.");
  if (
    f.contactAction === "polarity"
      ? slot !== c?.slot || c.polarity === f.polarity
      : !catalog.available_slots.includes(slot)
  )
    throw Error(
      "Choose an available input terminal or a different contact polarity.",
    );
  const instance = add ? Number(f.instance) : Number(c!.object.split(",")[1]);
  if (
    add &&
    (!f.name.trim() ||
      !/^\d+$/.test(f.instance) ||
      !Number.isSafeInteger(instance) ||
      instance < 1 ||
      instance > 4194302)
  )
    throw Error("Enter a point name and valid unused instance.");
  return {
    action: add
      ? "allocate-binary"
      : f.contactAction === "move"
        ? "binary-input-terminal"
        : "binary-input-polarity",
    slot,
    object_instance: instance,
    ...(add ? { name: f.name.trim() } : { expected_slot: c!.slot }),
    ...(f.contactAction === "move" ? {} : { polarity: f.polarity }),
  };
}

export function NativeContactFields({
  catalog,
  form,
  edit,
}: {
  catalog: ContactCatalog;
  form: ContactForm;
  edit: (patch: Partial<ContactForm>) => void;
}) {
  const source = catalog.contacts.find((c) => c.object === form.object);
  const usable = catalog.contacts.some((c) => !c.unavailable_reason);
  const free = catalog.available_slots.length > 0;
  return (
    <>
      <label>
        Input operation
        <select
          value={form.contactAction}
          onChange={(e) =>
            edit(
              selectContact(
                catalog,
                e.target.value as ContactAction,
                form.object,
              ),
            )
          }
        >
          <option value="add" disabled={!free}>
            Assign a new dry contact
          </option>
          <option value="move" disabled={!free || !usable}>
            Move an existing dry contact
          </option>
          <option value="polarity" disabled={!usable}>
            Change contact polarity
          </option>
        </select>
      </label>
      {form.contactAction !== "add" && (
        <label>
          Configured dry contact
          <select
            value={form.object}
            onChange={(e) =>
              edit(selectContact(catalog, form.contactAction, e.target.value))
            }
          >
            {catalog.contacts.map((c) => (
              <option
                key={c.object}
                value={c.object}
                disabled={!!c.unavailable_reason}
              >
                {c.name} · IN{c.slot}
                {c.unavailable_reason ? " · " + c.unavailable_reason : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {form.contactAction !== "polarity" && (
        <label>
          Destination input terminal
          <select
            value={form.slot}
            onChange={(e) => edit({ slot: e.target.value })}
          >
            {catalog.available_slots.map((n) => (
              <option key={n} value={n}>
                IN{n} · Universal input
              </option>
            ))}
          </select>
        </label>
      )}
      {form.contactAction === "add" && (
        <>
          <label>
            New point name
            <input
              maxLength={128}
              value={form.name}
              onChange={(e) => edit({ name: e.target.value })}
            />
          </label>
          <label>
            New point instance
            <input
              inputMode="numeric"
              value={form.instance}
              onChange={(e) => edit({ instance: e.target.value })}
            />
          </label>
        </>
      )}
      {form.contactAction !== "move" && (
        <label>
          Reported contact polarity
          <select
            value={form.polarity}
            onChange={(e) => edit({ polarity: e.target.value as Polarity })}
          >
            <option value="normal">Normal</option>
            <option value="reverse">Reverse</option>
          </select>
        </label>
      )}
      {source && form.contactAction !== "add" && (
        <p>
          {source.name} uses IN{source.slot}. Its saved polarity is{" "}
          {source.polarity ?? "controller-defined"}. Its inactive and active
          labels are {source.inactive_text} and {source.active_text}.
        </p>
      )}
      {!free && <p>All local universal input terminals are assigned.</p>}
      {!free && !usable && (
        <p>This application has no editable maintained dry contact.</p>
      )}
      {form.contactAction === "add" && free && (
        <p>
          The new input has independent Off and On states. Reverse polarity
          swaps the reported contact state.
        </p>
      )}
    </>
  );
}
