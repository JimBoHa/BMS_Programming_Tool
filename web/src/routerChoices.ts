export type RouterChoice = {
  router: string;
  networks: number[];
  truncated?: boolean;
  cached?: boolean;
  device?: string;
  ipDiscovered?: boolean;
  identityConflict?: boolean;
};

export const routerEndpoint = (value: string) =>
  value.trim() &&
  (value.includes(":") ? value.trim() : value.trim() + ":47808");

/** IP I-Am replies are candidates, not proof of downstream routing. */
export function routerChoices(
  advertised: RouterChoice[],
  devices: { address: string; device: string }[],
) {
  const choices = new Map<string, RouterChoice>();
  for (const row of advertised)
    choices.set(routerEndpoint(row.router), {
      ...row,
      networks: [...row.networks],
    });
  for (const device of devices) {
    const key = routerEndpoint(device.address),
      previous = choices.get(key);
    const conflict =
      previous?.identityConflict ||
      (!!previous?.device && previous.device !== device.device);
    choices.set(key, {
      ...previous,
      router: previous?.router || device.address,
      networks: previous?.networks || [],
      device: conflict ? undefined : device.device,
      identityConflict: conflict,
      ipDiscovered: true,
    });
  }
  return [...choices.values()];
}

export const routerIdentityKey = (row: RouterChoice) =>
  JSON.stringify([routerEndpoint(row.router), row.device]);
