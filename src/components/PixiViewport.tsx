// Based on https://codepen.io/inlet/pen/yLVmPWv.
// Copyright (c) 2018 Patrick Brouwer, distributed under the MIT license.

import { PixiComponent, useApp } from '@pixi/react';
import { Viewport } from 'pixi-viewport';
import { Application } from 'pixi.js';
import { MutableRefObject, ReactNode } from 'react';

export type ViewportProps = {
  app: Application;
  viewportRef?: MutableRefObject<Viewport | undefined>;

  screenWidth: number;
  screenHeight: number;
  worldWidth: number;
  worldHeight: number;
  children?: ReactNode;
};

// https://davidfig.github.io/pixi-viewport/jsdoc/Viewport.html
export default PixiComponent('Viewport', {
  create(props: ViewportProps) {
    const { app, children, viewportRef, ...viewportProps } = props;
    const viewport = new Viewport({
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access
      events: app.renderer.events,
      ...viewportProps,
    });
    if (viewportRef) {
      viewportRef.current = viewport;
    }
    // Activate plugins
    // Start centered on the world at a scale that fits the whole map
    const fitScale = Math.min(
      props.screenWidth / props.worldWidth,
      props.screenHeight / props.worldHeight,
    );
    viewport
      .drag()
      .pinch({})
      .decelerate({ friction: 0.97 })
      .clamp({ direction: 'all', underflow: 'center' })
      .clampZoom({
        minScale: Math.max(0.5, fitScale * 0.9),
        maxScale: 3.0,
      });
    // Start at a zoom that shows detail (1.5x) rather than fitting entire map
    const initialScale = Math.max(fitScale, 1.5);
    viewport.moveCenter(props.worldWidth / 2, props.worldHeight / 2);
    viewport.setZoom(initialScale);
    return viewport;
  },
  applyProps(viewport, oldProps: any, newProps: any) {
    Object.keys(newProps).forEach((p) => {
      if (p !== 'app' && p !== 'viewportRef' && p !== 'children' && oldProps[p] !== newProps[p]) {
        (viewport as any)[p] = newProps[p];
      }
    });
  },
});
