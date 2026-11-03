/** 开发服务器的 canonical origin。localStorage 按源隔离，127.0.0.1 和 localhost 会各存一份商品草稿。 */

export function canonicalDevOriginRedirect(href: string): string | null {
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || url.port !== "5173") return null;
  url.hostname = "localhost";
  const next = url.toString();
  return next === href ? null : next;
}

/** 命中回环开发地址时跳到 localhost，并保留 path、query、hash。已经是 localhost 则什么都不做。 */
export function redirectLoopbackDevOrigin(location: { href: string; replace: (url: string) => void }): boolean {
  const next = canonicalDevOriginRedirect(location.href);
  if (!next) return false;
  location.replace(next);
  return true;
}
