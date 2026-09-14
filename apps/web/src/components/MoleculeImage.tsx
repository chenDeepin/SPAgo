import { useEffect, useState } from "react";
import { api } from "../api/client";

interface MoleculeImageProps {
  compoundId: string;
}

/** Lazy structure depiction. The image keeps its layout box while loading
 * (a display:none lazy image never intersects the viewport, so it would never
 * fetch); the SVG fades in over the skeleton when ready. A failed depiction
 * degrades to a per-row placeholder. */
export function MoleculeImage({ compoundId }: MoleculeImageProps) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setFailed(false);
    setLoaded(false);
  }, [compoundId]);

  if (failed) {
    return (
      <div
        style={{ position: "relative", width: 144, height: 80 }}
        role="img"
        aria-label="Structure depiction unavailable"
      >
        <div className="depiction-failed">
          Structure
          <br />
          unavailable
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "relative", width: 144, height: 80 }} aria-busy={!loaded}>
      {!loaded && <div className="depiction skeleton" style={{ position: "absolute", inset: 0 }} />}
      <img
        className="depiction"
        style={{
          position: "absolute",
          inset: 0,
          opacity: loaded ? 1 : 0,
          transition: "opacity 150ms ease-in",
        }}
        src={api.depictionUrl(compoundId)}
        alt="2D structure depiction"
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
      />
    </div>
  );
}
