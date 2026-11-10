// Kakao Map JS SDK 의 최소 타입. 우리가 쓰는 것만 선언한다.
declare namespace kakao.maps {
  function load(cb: () => void): void

  class LatLng {
    constructor(lat: number, lng: number)
    getLat(): number
    getLng(): number
  }

  class LatLngBounds {
    constructor()
    extend(latlng: LatLng): void
  }

  class Map {
    constructor(container: HTMLElement, options: { center: LatLng; level?: number })
    setCenter(latlng: LatLng): void
    panTo(latlng: LatLng): void
    setBounds(bounds: LatLngBounds, paddingTop?: number, paddingRight?: number, paddingBottom?: number, paddingLeft?: number): void
    relayout(): void
    setLevel(level: number): void
  }

  class CustomOverlay {
    constructor(options: { position: LatLng; content: HTMLElement | string; yAnchor?: number; xAnchor?: number; zIndex?: number; clickable?: boolean })
    setMap(map: Map | null): void
  }

  class Polyline {
    constructor(options: {
      path: LatLng[]
      strokeWeight?: number
      strokeColor?: string
      strokeOpacity?: number
      strokeStyle?: 'solid' | 'shortdash' | 'dash' | 'dot' | 'shortdot' | 'dashdot'
      map?: Map
    })
    setMap(map: Map | null): void
  }
}
