"use client";

import { useEffect, useState } from "react";
import { UserRound } from "lucide-react";

type BuyerAvatarProps = {
  src?: string | null;
  name?: string | null;
  size?: "sm" | "md";
};

export function BuyerAvatar({ src, name, size = "md" }: BuyerAvatarProps) {
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [src]);

  return (
    <span className={`buyer-avatar buyer-avatar-${size}`} aria-hidden="true">
      {src && !failed ? (
        <img
          src={src}
          alt=""
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span title={name ? `${name}暂无头像` : "暂无头像"}>
          <UserRound size={size === "sm" ? 15 : 17} strokeWidth={1.7} />
        </span>
      )}
    </span>
  );
}
