// One shared lock allows multiple callers to release it independently.
const locks = new Set();
let restore = null;

export function lockScroll() {
  const token = {};
  if (locks.size === 0) {
    const body = document.body;
    const x = window.scrollX;
    const y = window.scrollY;
    const properties = ["position", "top", "left", "width", "overflow", "padding-right"];
    const styles = properties.map((name) => [
      name, body.style.getPropertyValue(name), body.style.getPropertyPriority(name),
    ]);
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;
    const padding = parseFloat(getComputedStyle(body).paddingRight) || 0;
    body.style.position = "fixed";
    body.style.top = `-${y}px`;
    body.style.left = `-${x}px`;
    body.style.width = "100%";
    body.style.overflow = "hidden";
    body.style.paddingRight = `${padding + scrollbar}px`;
    restore = () => {
      for (const [name, value, priority] of styles) {
        if (value) body.style.setProperty(name, value, priority);
        else body.style.removeProperty(name);
      }
      const root = document.documentElement;
      const behavior = root.style.getPropertyValue("scroll-behavior");
      const priority = root.style.getPropertyPriority("scroll-behavior");
      root.style.setProperty("scroll-behavior", "auto", "important");
      window.scrollTo(x, y);
      if (behavior) root.style.setProperty("scroll-behavior", behavior, priority);
      else root.style.removeProperty("scroll-behavior");
    };
  }
  locks.add(token);
  return () => {
    if (!locks.delete(token)) return;
    if (locks.size === 0) {
      restore();
      restore = null;
    }
  };
}
