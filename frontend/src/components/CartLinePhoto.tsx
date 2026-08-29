import { useEffect, useState } from "react";
import { Image } from "antd";

import { getCartLinePhotoUrl } from "@/api/carts";

/**
 * Crop cận cảnh sản phẩm lúc AI detect. Blob JWT giống ảnh khách —
 * unmount phải revoke URL.
 */
export default function CartLinePhoto({
  cartId,
  lineId,
  size = 48,
  alt = "Crop sản phẩm",
}: {
  cartId: string;
  lineId: string;
  size?: number;
  alt?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    getCartLinePhotoUrl(cartId, lineId)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        objectUrl = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [cartId, lineId]);

  if (!url) {
    return (
      <div
        style={{
          width: size,
          height: size,
          borderRadius: 6,
          background: "#f5f5f5",
          border: "1px solid #d9d9d9",
          flexShrink: 0,
        }}
      />
    );
  }
  return (
    <Image
      src={url}
      alt={alt}
      width={size}
      height={size}
      style={{
        objectFit: "cover",
        borderRadius: 6,
        border: "1px solid #d9d9d9",
        flexShrink: 0,
      }}
      preview={{ mask: alt || "Xem cận cảnh" }}
    />
  );
}
