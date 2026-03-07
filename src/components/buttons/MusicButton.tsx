import { useCallback, useEffect, useState } from 'react';
import volumeImg from '../../../assets/volume.svg';
import { sound } from '@pixi/sound';
import Button from './Button';

export default function MusicButton() {
  const [isPlaying, setPlaying] = useState(false);

  const flipSwitch = async () => {
    if (isPlaying) {
      sound.stop('background');
    } else {
      await sound.play('background');
    }
    setPlaying(!isPlaying);
  };

  const handleKeyPress = useCallback(
    (event: { key: string }) => {
      if (event.key === 'm' || event.key === 'M') {
        void flipSwitch();
      }
    },
    [flipSwitch],
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [handleKeyPress]);

  return (
    <Button
      onClick={() => void flipSwitch()}
      className="hidden lg:block"
      title="Play AI generated music (press m to play/mute)"
      imgUrl={volumeImg}
    >
      {isPlaying ? 'Mute' : 'Music'}
    </Button>
  );
}
