import Transcript from "../components/Transcript";
import InputBar from "../components/InputBar";

interface Props {
  onSend: (text: string) => void;
}

export default function ChatPage({ onSend }: Props) {
  return (
    <>
      <Transcript />
      <InputBar onSend={onSend} />
    </>
  );
}
