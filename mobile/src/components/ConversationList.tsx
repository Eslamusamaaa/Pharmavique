// The saved conversations beside the assistant (ADR-022): new conversation, search, and for each
// one rename, pin, share and delete. Actions open inline under the row: the website has no
// system dialogs (react-native-web's Alert does nothing).
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Platform, Pressable, ScrollView, Share, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { friendlyError, type Level } from '@/api/client';
import {
  deleteAllConversations,
  deleteConversation,
  listConversations,
  pinConversation,
  renameConversation,
  shareConversation,
  shareLink,
  unshareConversation,
  type ConversationList as ListData,
  type ConversationSummary,
} from '@/api/conversations';
import {
  DotsThreeVerticalIcon,
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  PlusIcon,
  PushPinIcon,
  PushPinSlashIcon,
  ShareNetworkIcon,
  TrashIcon,
  XIcon,
} from '@/components/icons';
import { PrimaryButton, Row, T } from '@/components/ui';
import { fonts, radius, useTheme } from '@/theme';

function when(at: string): string {
  return new Date(at).toLocaleDateString('ar-SA-u-nu-latn', { month: 'short', day: 'numeric' });
}

async function offerLink(url: string): Promise<'shared' | 'copied' | 'shown'> {
  if (Platform.OS === 'web') {
    const nav = typeof navigator !== 'undefined' ? navigator : undefined;
    if (nav?.share) {
      try {
        await nav.share({ url });
        return 'shared';
      } catch {
        // closed by the person: fall through to copying
      }
    }
    try {
      await nav?.clipboard?.writeText(url);
      return 'copied';
    } catch {
      return 'shown';
    }
  }
  await Share.share({ message: url });
  return 'shared';
}

export function ConversationList({
  visible,
  onClose,
  currentId,
  onOpen,
  onNew,
  level,
}: {
  visible: boolean;
  onClose: () => void;
  currentId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  level?: Level; // only an operator's choice is read by the server
}) {
  const { c } = useTheme();
  const [query, setQuery] = useState('');
  const [data, setData] = useState<ListData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const request = useRef(0);

  const load = useCallback(
    async (q: string) => {
      const mine = ++request.current;
      setLoading(true);
      try {
        const list = await listConversations(q, level);
        if (mine === request.current) {
          setData(list);
          setError(null);
        }
      } catch (e) {
        if (mine === request.current) setError(friendlyError(e));
      } finally {
        if (mine === request.current) setLoading(false);
      }
    },
    [level],
  );

  useEffect(() => {
    if (!visible) return;
    const timer = setTimeout(() => load(query), query ? 300 : 0);
    return () => clearTimeout(timer);
  }, [visible, query, load]);

  const refresh = () => load(query);
  const items = data?.conversations ?? [];
  const nearlyFull = data ? data.total >= data.warn_at : false;

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={[styles.backdrop, { backgroundColor: 'rgba(0,0,0,0.25)' }]}>
        <SafeAreaView edges={['top', 'bottom']} style={[styles.sheet, { backgroundColor: c.bg }]}>
          <Row gap={8} style={styles.top}>
            <T size={18} weight={700} style={{ flex: 1 }}>
              محادثاتي
            </T>
            <Pressable onPress={onClose} style={styles.iconBtn} accessibilityRole="button" accessibilityLabel="إغلاق">
              <XIcon size={22} color={c.ink} />
            </Pressable>
          </Row>
          <View style={{ paddingHorizontal: 16, gap: 10 }}>
            <PrimaryButton
              label="محادثة جديدة"
              icon={<PlusIcon size={18} color={c.prt} />}
              onPress={() => {
                onNew();
                onClose();
              }}
            />
            <Row gap={6} style={[styles.search, { backgroundColor: c.sf, borderColor: c.ln }]}>
              <MagnifyingGlassIcon size={18} color={c.ink2} />
              <TextInput
                value={query}
                onChangeText={setQuery}
                placeholder="ابحث في محادثاتك"
                placeholderTextColor={c.ink2}
                style={[styles.searchInput, { color: c.ink, fontFamily: fonts.ar[400] }]}
                accessibilityLabel="ابحث في محادثاتك"
              />
            </Row>
            {nearlyFull && data ? (
              <T size={12.5} color={c.wn}>
                {`عندك ${data.total} محادثة من ${data.limit}. لما توصل ${data.limit}، أقدم محادثة مو مثبتة تنحذف تلقائيًا.`}
              </T>
            ) : null}
          </View>

          <ScrollView contentContainerStyle={styles.list} keyboardShouldPersistTaps="handled">
            {loading && !data ? <ActivityIndicator color={c.ink2} /> : null}
            {error ? (
              <T size={14} color={c.rd}>
                {error}
              </T>
            ) : null}
            {data && items.length === 0 ? (
              <T size={14} color={c.ink2}>
                {query ? 'ما لقينا محادثة فيها هالكلمة.' : 'ما عندك محادثات محفوظة للحين. اسأل المساعد وتنحفظ هنا.'}
              </T>
            ) : null}
            {items.map((item) => (
              <ConversationRow
                key={item.id}
                item={item}
                current={item.id === currentId}
                expanded={openRow === item.id}
                pinFull={data ? items.filter((i) => i.pinned).length >= data.max_pinned : false}
                onToggle={() => setOpenRow((open) => (open === item.id ? null : item.id))}
                onOpen={() => {
                  onOpen(item.id);
                  onClose();
                }}
                onChanged={refresh}
                onDeleted={(id) => {
                  if (id === currentId) onNew();
                  refresh();
                }}
              />
            ))}
            {data && data.total > 0 && !query ? (
              confirmAll ? (
                <View style={[styles.confirm, { borderColor: c.rd }]}>
                  <T size={14} weight={600}>
                    {`نحذف كل المحادثات (${data.total})؟ ما نقدر نرجّعها بعد الحذف.`}
                  </T>
                  <Row gap={8}>
                    <Pressable
                      onPress={async () => {
                        await deleteAllConversations(level).catch(() => undefined);
                        setConfirmAll(false);
                        onNew();
                        refresh();
                      }}
                      style={[styles.smallBtn, { backgroundColor: c.rd }]}
                      accessibilityRole="button"
                    >
                      <T size={14} weight={700} color="#FFFFFF">
                        احذف الكل
                      </T>
                    </Pressable>
                    <Pressable onPress={() => setConfirmAll(false)} style={[styles.smallBtn, { borderColor: c.ln, borderWidth: 1 }]} accessibilityRole="button">
                      <T size={14}>تراجع</T>
                    </Pressable>
                  </Row>
                </View>
              ) : (
                <Pressable onPress={() => setConfirmAll(true)} style={styles.deleteAll} accessibilityRole="button">
                  <TrashIcon size={16} color={c.rd} />
                  <T size={14} color={c.rd}>
                    احذف كل المحادثات
                  </T>
                </Pressable>
              )
            ) : null}
          </ScrollView>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

function ConversationRow({
  item,
  current,
  expanded,
  pinFull,
  onToggle,
  onOpen,
  onChanged,
  onDeleted,
}: {
  item: ConversationSummary;
  current: boolean;
  expanded: boolean;
  pinFull: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onChanged: () => void;
  onDeleted: (id: string) => void;
}) {
  const { c } = useTheme();
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(item.share_token ? shareLink(`/shared/${item.share_token}`) : null);

  // `work` may return the note to show (for example "we copied the link"); else `done` is shown
  const act = async (work: () => Promise<unknown>, done?: string) => {
    try {
      const said = await work();
      setNote(typeof said === 'string' ? said : (done ?? null));
      onChanged();
    } catch (e) {
      setNote(friendlyError(e));
    }
  };

  return (
    <View style={[styles.row, { backgroundColor: current ? c.prs : c.sf, borderColor: c.ln }]}>
      <Row gap={8}>
        <Pressable onPress={onOpen} style={{ flex: 1, gap: 2 }} accessibilityRole="button" accessibilityLabel={item.title}>
          <Row gap={6}>
            {item.pinned ? <PushPinIcon size={14} color={c.pr} weight="fill" /> : null}
            {item.shared ? <ShareNetworkIcon size={14} color={c.ink2} /> : null}
            <T size={15} weight={600} numberOfLines={1} style={{ flex: 1 }}>
              {item.title}
            </T>
          </Row>
          <T size={12} color={c.ink2}>
            {when(item.updated_at)}
          </T>
        </Pressable>
        <Pressable onPress={onToggle} style={styles.iconBtn} accessibilityRole="button" accessibilityLabel="خيارات المحادثة" aria-expanded={expanded}>
          <DotsThreeVerticalIcon size={22} color={c.ink2} weight="bold" />
        </Pressable>
      </Row>

      {expanded ? (
        <View style={{ gap: 8, marginTop: 8 }}>
          {renaming ? (
            <Row gap={8}>
              <TextInput
                value={title}
                onChangeText={setTitle}
                autoFocus
                maxLength={120}
                style={[styles.renameInput, { color: c.ink, borderColor: c.ln, backgroundColor: c.bg, fontFamily: fonts.ar[400] }]}
                accessibilityLabel="اسم المحادثة"
                onSubmitEditing={() => act(() => renameConversation(item.id, title)).then(() => setRenaming(false))}
              />
              <Pressable
                onPress={() => act(() => renameConversation(item.id, title)).then(() => setRenaming(false))}
                style={[styles.smallBtn, { backgroundColor: c.pr }]}
                accessibilityRole="button"
              >
                <T size={14} weight={700} color={c.prt}>
                  حفظ
                </T>
              </Pressable>
            </Row>
          ) : null}
          <Row gap={8} style={{ flexWrap: 'wrap' }}>
            <Action label="غيّر الاسم" icon={<PencilSimpleIcon size={16} color={c.ink} />} onPress={() => setRenaming((r) => !r)} />
            <Action
              label={item.pinned ? 'ألغِ التثبيت' : 'ثبّت'}
              icon={item.pinned ? <PushPinSlashIcon size={16} color={c.ink} /> : <PushPinIcon size={16} color={c.ink} />}
              onPress={() =>
                !item.pinned && pinFull
                  ? setNote('ثبّت 10 محادثات بحد أقصى. ألغِ تثبيت وحدة أول.')
                  : act(() => pinConversation(item.id, !item.pinned))
              }
            />
            <Action
              label={item.shared ? 'حدّث الرابط' : 'شارك برابط'}
              icon={<ShareNetworkIcon size={16} color={c.ink} />}
              onPress={() =>
                act(async () => {
                  const { path } = await shareConversation(item.id);
                  const url = shareLink(path);
                  setLink(url);
                  const how = await offerLink(url);
                  return how === 'copied' ? 'نسخنا الرابط. أي أحد معه الرابط يقدر يشوف المحادثة.' : 'أي أحد معه الرابط يقدر يشوف المحادثة.';
                })
              }
            />
            <Action label="احذف" icon={<TrashIcon size={16} color={c.rd} />} danger onPress={() => setConfirmDelete(true)} />
          </Row>
          {link && item.shared ? (
            <View style={{ gap: 6 }}>
              <T size={12.5} color={c.ink2} numberOfLines={2} latin>
                {link}
              </T>
              <Pressable
                onPress={() => act(() => unshareConversation(item.id), 'وقّفنا المشاركة. الرابط ما عاد يفتح.').then(() => setLink(null))}
                accessibilityRole="button"
              >
                <T size={13} weight={600} color={c.rd}>
                  أوقف المشاركة
                </T>
              </Pressable>
            </View>
          ) : null}
          {confirmDelete ? (
            <View style={[styles.confirm, { borderColor: c.rd }]}>
              <T size={14} weight={600}>
                نحذف هالمحادثة؟ ما نقدر نرجّعها، ورابط المشاركة يوقف.
              </T>
              <Row gap={8}>
                <Pressable
                  onPress={async () => {
                    try {
                      await deleteConversation(item.id);
                      onDeleted(item.id);
                    } catch (e) {
                      setNote(friendlyError(e));
                    }
                  }}
                  style={[styles.smallBtn, { backgroundColor: c.rd }]}
                  accessibilityRole="button"
                >
                  <T size={14} weight={700} color="#FFFFFF">
                    احذف
                  </T>
                </Pressable>
                <Pressable onPress={() => setConfirmDelete(false)} style={[styles.smallBtn, { borderColor: c.ln, borderWidth: 1 }]} accessibilityRole="button">
                  <T size={14}>تراجع</T>
                </Pressable>
              </Row>
            </View>
          ) : null}
          {note ? (
            <T size={12.5} color={c.ink2}>
              {note}
            </T>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function Action({ label, icon, onPress, danger }: { label: string; icon: React.ReactNode; onPress: () => void; danger?: boolean }) {
  const { c } = useTheme();
  return (
    <Pressable onPress={onPress} style={[styles.action, { borderColor: danger ? c.rd : c.ln }]} accessibilityRole="button">
      {icon}
      <T size={13} weight={600} color={danger ? c.rd : c.ink}>
        {label}
      </T>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, flexDirection: 'row' },
  sheet: { width: '88%', maxWidth: 420, height: '100%', marginLeft: 'auto' },
  top: { paddingHorizontal: 12, paddingVertical: 8, minHeight: 56 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  search: { borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 12, minHeight: 48 },
  // 16 px: a smaller font makes the iPhone zoom into the box and stay zoomed
  searchInput: { flex: 1, minWidth: 0, fontSize: 16, textAlign: 'right', writingDirection: 'rtl', paddingVertical: 10 },
  list: { padding: 16, gap: 10, paddingBottom: 40 },
  row: { borderWidth: 1, borderRadius: radius.md, paddingVertical: 8, paddingRight: 12, paddingLeft: 4 },
  action: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: radius.pill, paddingVertical: 8, paddingHorizontal: 12, minHeight: 40 },
  smallBtn: { borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: 16, minHeight: 44, justifyContent: 'center' },
  renameInput: { flex: 1, minWidth: 0, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 12, minHeight: 44, fontSize: 16, textAlign: 'right', writingDirection: 'rtl' },
  confirm: { borderWidth: 1, borderRadius: radius.md, padding: 12, gap: 10 },
  deleteAll: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 14 },
});
