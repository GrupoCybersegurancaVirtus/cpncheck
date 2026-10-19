use (ogpath^"ASKCTL/ASKCTLloader.sml");
(* Somebody is eating *)
fun Eating n = Mark.Top'Eat 1 n <> empty;
fun TwoEat n = size (Mark.Top'Eat 1 n) >= 2;
fun IsPut a = case ArcToBE a of Bind.Top'Put_Down_Chopsticks (1, {p}) => p = ph(1) | _ => false;
fun IsTake a = case ArcToTI a of TI.Top'Take_Chopsticks 1 => true | _ => false;
val CanEat = eval_node (POS (NF ("eating", Eating))) InitNode;
val AlwaysAgain = eval_node (INV (POS (NF ("eating", Eating)))) InitNode;
val NeverTwo = eval_node (INV (NOT (NF ("two", TwoEat)))) InitNode;
eval_node (EV (NF ("eating", Eating))) InitNode;
eval_node (POS (EXIST_MODAL (AF ("put ph1", IsPut), TT))) InitNode;
eval_node (FORALL_NEXT (MODAL (AF ("take", IsTake)))) InitNode;
eval_node (ALONG (NOT (NF ("eating", Eating)))) InitNode;
eval_node (POS (ALONG (NOT (NF ("eating", Eating))))) InitNode;
eval_node (EV (INV (NF ("eating", Eating)))) InitNode;
val Count = length (PredAllNodes Eating) > 0 andalso NoOfNodes () > 1;
