(* ASK-CTL queries for examples/nets/dining.cpn, as CPN Tools takes them. *)
use (ogpath^"ASKCTL/ASKCTLloader.sml");

fun Eating n = Mark.Top'Eat 1 n <> empty;
fun TwoEat n = size (Mark.Top'Eat 1 n) >= 2;
fun PutsDown1 a = case ArcToBE a of
    Bind.Top'Put_Down_Chopsticks (1, {p}) => p = ph(1)
  | _ => false;

(* Somebody can always eat again. *)
val AlwaysAgain = eval_node (INV (POS (NF ("eating", Eating)))) InitNode;
(* Two philosophers never eat together (false: 1 and 3 can). *)
val NeverTwo = eval_node (INV (NOT (NF ("two", TwoEat)))) InitNode;
(* Philosopher 1 can put the chopsticks down: an arc formula. *)
val CanPut1 = eval_node (POS (EXIST_MODAL (AF ("put 1", PutsDown1), TT))) InitNode;
(* Somebody eventually eats. *)
eval_node (EV (NF ("eating", Eating))) InitNode;
(* The same, with the predicate inline. *)
eval_node (POS (EXIST_MODAL (AF ("put", fn a => ArcToTI a = TI.Top'Put_Down_Chopsticks 1), TT))) InitNode;
