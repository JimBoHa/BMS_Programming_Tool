import { useEffect, useRef, useState } from "react";
import { api } from "./api";

type NetworkChoice = {
  address: string;
  name: string;
  network: string;
  recommended: boolean;
  broadcast_available: boolean;
};

export function ComputerNetworkPicker({
  value,
  disabled,
  allowSuggestion,
  onChoose,
  onSuggest,
}: {
  value: string;
  disabled: boolean;
  allowSuggestion: boolean;
  onChoose: (address: string) => void;
  onSuggest: (address: string) => void;
}) {
  const [choices, setChoices] = useState<NetworkChoice[]>([]);
  const [error, setError] = useState("");
  const suggested = useRef(false);
  const callbacks = useRef({ onSuggest });
  callbacks.current = { onSuggest };
  useEffect(() => {
    let current = true;
    void api("/bacnet/interfaces")
      .then((report) => {
        if (current) setChoices(report.interfaces);
      })
      .catch((failure) => {
        if (current) setError(String(failure));
      });
    return () => {
      current = false;
    };
  }, []);
  useEffect(() => {
    if (!allowSuggestion || suggested.current || disabled) return;
    const recommended =
      choices.find((row) => row.recommended) ||
      (choices.length === 1 ? choices[0] : undefined);
    if (recommended) {
      suggested.current = true;
      callbacks.current.onSuggest(recommended.address);
    }
  }, [choices, allowSuggestion, disabled]);
  const selected = choices.find(
    (row) => row.address === value.split(":")[0].split("/")[0],
  );
  return (
    <div className="full computer-network-picker">
      <label>
        Computer network
        <select
          aria-label="Computer network"
          disabled={disabled || !choices.length}
          value={selected?.address || ""}
          onChange={(event) => onChoose(event.target.value)}
        >
          <option value="" disabled>
            {choices.length
              ? "Choose the network connected to your building"
              : "Use a computer IP below"}
          </option>
          {choices.map((row) => (
            <option key={`${row.address}/${row.network}`} value={row.address}>
              {row.recommended ? "Recommended · " : ""}
              {row.name} · {row.address} · {row.network}
            </option>
          ))}
        </select>
      </label>
      <p className="help-text">
        Choose the network your computer uses to reach the building controls,
        then Open interface to continue. The computer address below is filled
        for you. Searching starts only when you choose Find NAEs &amp; routers.
      </p>
      {selected && !selected.broadcast_available && (
        <p role="status">
          This network has no local broadcast range. Use an engine IP address or
          choose the building’s Ethernet / Wi-Fi connection.
        </p>
      )}
      {error && (
        <p role="status">
          Computer networks could not be listed. Enter the computer IP below.{" "}
          {error}
        </p>
      )}
    </div>
  );
}
