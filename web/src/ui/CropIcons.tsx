/**
 * Inline SVG line-art crop icons for Krishi Bazaar.
 * Line-art style: no fill, 1.5px stroke, 24×24 viewBox.
 * Used in chips, setup, board rows, etc.
 */

interface CropIconProps {
  size?: number;
  stroke?: string;
  className?: string;
  'aria-hidden'?: boolean | 'true' | 'false';
}

export function IconOnion({ size = 20, stroke = 'currentColor', className, ...rest }: CropIconProps) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke={stroke} strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round"
      className={className} aria-hidden {...rest}
    >
      {/* Bulb */}
      <path d="M12 4 C8 4 5 7.5 5 11 C5 15 8 18 12 18 C16 18 19 15 19 11 C19 7.5 16 4 12 4Z" />
      {/* Tip/stem */}
      <path d="M12 4 L12 1.5" />
      {/* Leaf curl */}
      <path d="M12 2 C12 2 14 0.5 15.5 2" />
      {/* Roots */}
      <path d="M9 18 L8 21" />
      <path d="M12 18 L12 21" />
      <path d="M15 18 L16 21" />
    </svg>
  );
}

export function IconTomato({ size = 20, stroke = 'currentColor', className, ...rest }: CropIconProps) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke={stroke} strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round"
      className={className} aria-hidden {...rest}
    >
      {/* Round fruit */}
      <circle cx="12" cy="14" r="7" />
      {/* Stem */}
      <path d="M12 7 L12 4" />
      {/* Leaf left */}
      <path d="M12 5 C10 3 7.5 4 8 6" />
      {/* Leaf right */}
      <path d="M12 5 C14 3 16.5 4 16 6" />
      {/* Small centre cross (calyx) */}
      <path d="M10 7 C11 6 13 6 14 7" />
    </svg>
  );
}

export function IconSoybean({ size = 20, stroke = 'currentColor', className, ...rest }: CropIconProps) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke={stroke} strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round"
      className={className} aria-hidden {...rest}
    >
      {/* Pod outline */}
      <path d="M7 20 C4 18 4 6 7 4 C9 3 11 4 12 6" />
      <path d="M17 20 C20 18 20 6 17 4 C15 3 13 4 12 6" />
      <path d="M7 4 C9.5 2 14.5 2 17 4" />
      <path d="M7 20 C9.5 22 14.5 22 17 20" />
      {/* 3 beans inside */}
      <ellipse cx="12" cy="8"  rx="2" ry="1.5" />
      <ellipse cx="12" cy="12" rx="2" ry="1.5" />
      <ellipse cx="12" cy="16" rx="2" ry="1.5" />
    </svg>
  );
}

export function IconMaize({ size = 20, stroke = 'currentColor', className, ...rest }: CropIconProps) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke={stroke} strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round"
      className={className} aria-hidden {...rest}
    >
      {/* Cob body */}
      <rect x="9" y="6" width="6" height="14" rx="3" />
      {/* Kernel lines (horizontal) */}
      <path d="M9 9 L15 9" />
      <path d="M9 12 L15 12" />
      <path d="M9 15 L15 15" />
      {/* Husk leaf left */}
      <path d="M9 8 C6 7 5 4 8 3" />
      {/* Husk leaf right */}
      <path d="M15 8 C18 7 19 4 16 3" />
      {/* Tassel/silk at top */}
      <path d="M11 6 L10 2" />
      <path d="M12 6 L12 1.5" />
      <path d="M13 6 L14 2" />
    </svg>
  );
}

/** Returns the appropriate crop SVG for a commodity ID. */
export function CropIcon({
  commodityId,
  size = 20,
  stroke = 'currentColor',
  className,
}: {
  commodityId: string;
  size?: number;
  stroke?: string;
  className?: string;
}) {
  const id = commodityId.toLowerCase();
  if (id.includes('onion') || id.includes('kanda') || id.includes('kandaa'))
    return <IconOnion size={size} stroke={stroke} className={className} aria-hidden />;
  if (id.includes('tomato') || id.includes('tamato'))
    return <IconTomato size={size} stroke={stroke} className={className} aria-hidden />;
  if (id.includes('soya') || id.includes('soy'))
    return <IconSoybean size={size} stroke={stroke} className={className} aria-hidden />;
  if (id.includes('maize') || id.includes('maka') || id.includes('corn'))
    return <IconMaize size={size} stroke={stroke} className={className} aria-hidden />;
  // Default: generic leaf
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d="M12 22V12"/><path d="M12 12C12 12 4 10 4 4C8 4 12 8 12 12Z"/><path d="M12 12C12 12 20 10 20 4C16 4 12 8 12 12Z"/>
    </svg>
  );
}
