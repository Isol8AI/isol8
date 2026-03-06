import { Stage, Sprite, Container } from '@pixi/react';
import { useElementSize } from 'usehooks-ts';
import { ApartmentAgent } from '../hooks/useApartment';

// Apartment image natural dimensions (approximate from the PNG)
const APT_WIDTH = 1456;
const APT_HEIGHT = 968;

interface Props {
  agents: ApartmentAgent[];
}

export default function ApartmentMap({ agents }: Props) {
  const [containerRef, { width, height }] = useElementSize();

  const scale = Math.min(
    width > 0 ? width / APT_WIDTH : 1,
    height > 0 ? height / APT_HEIGHT : 1,
  );

  return (
    <div ref={containerRef} className="w-full h-full">
      {width > 0 && height > 0 && (
        <Stage
          width={width}
          height={height}
          options={{ backgroundColor: 0x2a1f1a }}
        >
          <Container
            x={(width - APT_WIDTH * scale) / 2}
            y={(height - APT_HEIGHT * scale) / 2}
            scale={scale}
          >
            <Sprite
              image="/assets/apartment.png"
              x={0}
              y={0}
              width={APT_WIDTH}
              height={APT_HEIGHT}
            />
          </Container>
        </Stage>
      )}
    </div>
  );
}
