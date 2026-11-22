// The old "my list" screen became the أدويتي tab; this keeps any old link working.
import { Redirect } from 'expo-router';

export default function MyList() {
  return <Redirect href="/medicines" />;
}
