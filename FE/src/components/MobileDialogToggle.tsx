import { IconChevronDown } from "@tabler/icons-react";

interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

export function MobileDialogToggle({ collapsed, onToggle }: Props) {
  return (
    <button
      className="mobile-dialog-toggle"
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      aria-label={collapsed ? "Mostrar modal" : "Ocultar modal"}
      title={collapsed ? "Mostrar modal" : "Ocultar modal"}
    >
      <IconChevronDown aria-hidden="true" />
    </button>
  );
}
