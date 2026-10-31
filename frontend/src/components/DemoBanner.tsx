import { useEffect, useState } from "react";
import { getPublicSettings } from "../api/client";

// Shown only when the backend sets DEMO_NOTICE (the public demo deployment).
export default function DemoBanner() {
  const [notice, setNotice] = useState<string | null>(null);
  const [retention, setRetention] = useState<number | null>(null);

  useEffect(() => {
    getPublicSettings()
      .then((s) => {
        setNotice(s.demo_notice);
        setRetention(s.retention_hours);
      })
      .catch(() => undefined); // no banner if settings are unavailable
  }, []);

  if (!notice) return null;
  return (
    <div className="demo-banner" role="note">
      {notice}
      {retention && <span className="demo-banner-retention"> Files and chats are deleted after {retention} h.</span>}
    </div>
  );
}
