"use client";

// Leaflet map (loaded client-side only). Modes:
//  - display: show one or more polygons/points (field boundaries, coarse grid cells)
//  - draw:    tap to add boundary vertices; returns a GeoJSON Polygon (or Point)
// Base map: OpenStreetMap tiles (attribution required; dev/pilot use within the OSM tile policy).

import { useEffect, useRef } from "react";
import type * as L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useI18n } from "@/lib/i18n";

export interface MapShape {
  geometry: GeoJSON.Geometry;
  label?: string;
  className?: string;
}

interface Props {
  shapes?: MapShape[];
  draw?: boolean;
  vertices?: [number, number][]; // [lat, lon]
  onVerticesChange?: (v: [number, number][]) => void;
  center?: [number, number];
  zoom?: number;
  height?: number;
  ariaLabel: string;
}

export default function MapView({ shapes = [], draw = false, vertices = [], onVerticesChange, center = [19.5, 76.0], zoom = 7, height = 280, ariaLabel }: Props) {
  const { t } = useI18n();
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const lib = useRef<typeof L | null>(null);
  const cb = useRef(onVerticesChange);
  const vRef = useRef(vertices);
  cb.current = onVerticesChange;
  vRef.current = vertices;

  useEffect(() => {
    let cancelled = false;
    void import("leaflet").then((leaflet) => {
      if (cancelled || !el.current || map.current) return;
      lib.current = leaflet;
      const m = leaflet.map(el.current, { zoomControl: true, attributionControl: true }).setView(center, zoom);
      leaflet
        .tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" })
        .addTo(m);
      layer.current = leaflet.layerGroup().addTo(m);
      if (draw) m.on("click", (e: L.LeafletMouseEvent) => cb.current?.([...vRef.current, [e.latlng.lat, e.latlng.lng]]));
      map.current = m;
      render();
    });
    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const render = () => {
    const leaflet = lib.current;
    const m = map.current;
    const g = layer.current;
    if (!leaflet || !m || !g) return;
    g.clearLayers();
    const bounds: L.LatLngBounds[] = [];
    for (const s of shapes) {
      const gj = leaflet.geoJSON(s.geometry as GeoJSON.GeoJsonObject, {
        style: { color: "#2a78d6", weight: 2, fillOpacity: 0.15, className: s.className },
        pointToLayer: (_f, ll) => leaflet.circleMarker(ll, { radius: 7, color: "#2a78d6", weight: 2 }),
      });
      if (s.label) gj.bindTooltip(s.label);
      gj.addTo(g);
      bounds.push(gj.getBounds());
    }
    if (draw && vertices.length) {
      vertices.forEach((v) => leaflet.circleMarker(v, { radius: 5, color: "#eb6834", weight: 2 }).addTo(g));
      if (vertices.length > 1) leaflet.polygon(vertices, { color: "#eb6834", weight: 2, fillOpacity: 0.1, dashArray: "4" }).addTo(g);
    }
    if (bounds.length && !draw) {
      const b = bounds.reduce((acc, x) => acc.extend(x), bounds[0]);
      if (b.isValid()) m.fitBounds(b.pad(0.4), { maxZoom: 16 });
    }
  };

  useEffect(render);

  return (
    <div className="map-wrap">
      <div ref={el} style={{ height }} role="application" aria-label={ariaLabel} />
      {draw ? <p className="small muted">{t("map.draw_hint")}</p> : null}
    </div>
  );
}
